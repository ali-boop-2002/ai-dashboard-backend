"""
Pinecone routes: upload a document, convert to PDF, extract text, and index in Pinecone.

- POST /pinecone/upload: accepts pdf, docx, txt, csv, image. Converts to PDF and upserts chunks to Pinecone.
"""
import base64
import hashlib
import mimetypes
from io import BytesIO
from typing import List, Optional, Tuple
from uuid import uuid4

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from langchain_core.messages import HumanMessage
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter
from pinecone import Pinecone
from pypdf import PdfReader
from fpdf import FPDF
from PIL import Image
from docx import Document as DocxDocument

from app.core.auth import User, get_current_user
from app.api.deps import get_db
from app.models.document import Document as DocumentModel
from sqlalchemy.orm import Session
from app.core.config import settings
from app.core.audit import log_audit

router = APIRouter(prefix="/pinecone", tags=["pinecone"])

ALLOWED_TYPES = {
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "text/plain",
    "text/csv",
    "image/png",
    "image/jpeg",
    "image/webp",
    "image/gif",
}

MAX_UPLOAD_MB = 20


def _require_pinecone() -> Pinecone:
    if not settings.PINECONE_API_KEY or not settings.PINECONE_INDEX_NAME:
        raise HTTPException(
            status_code=503,
            detail="Pinecone is not configured. Set PINECONE_API_KEY and PINECONE_INDEX_NAME in .env.",
        )
    return Pinecone(api_key=settings.PINECONE_API_KEY)


def _decode_text(data: bytes) -> str:
    for enc in ("utf-8", "utf-16", "latin-1"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="ignore")


def _text_to_pdf_bytes(text: str) -> bytes:
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    pdf.set_font("Helvetica", size=11)
    for line in text.splitlines() or [""]:
        pdf.multi_cell(0, 6, line)
    return bytes(pdf.output(dest="S"))


def _docx_to_text(data: bytes) -> str:
    doc = DocxDocument(BytesIO(data))
    parts = [p.text for p in doc.paragraphs if p.text]
    return "\n".join(parts).strip()


def _pdf_to_text(pdf_bytes: bytes) -> str:
    reader = PdfReader(BytesIO(pdf_bytes))
    texts: List[str] = []
    for page in reader.pages:
        texts.append(page.extract_text() or "")
    return "\n".join(t for t in texts if t).strip()


def _image_to_pdf_bytes(data: bytes) -> bytes:
    img = Image.open(BytesIO(data))
    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")
    out = BytesIO()
    img.save(out, format="PDF")
    return out.getvalue()


def _image_to_text_via_vision(data: bytes, content_type: str) -> str:
    if not settings.OPENAI_API_KEY:
        raise HTTPException(
            status_code=503,
            detail="OPENAI_API_KEY is required to extract text from images.",
        )
    b64 = base64.standard_b64encode(data).decode("utf-8")
    data_url = f"data:{content_type};base64,{b64}"
    llm = ChatOpenAI(
        model="gpt-4o-mini",
        api_key=settings.OPENAI_API_KEY,
        max_tokens=1024,
    )
    message = HumanMessage(
        content=[
            {"type": "image_url", "image_url": {"url": data_url}},
            {"type": "text", "text": "Extract all readable text from this document image. Return plain text only."},
        ]
    )
    response = llm.invoke([message])
    return (response.content or "").strip() if hasattr(response, "content") else ""


def _convert_to_pdf_and_text(
    data: bytes, content_type: str, filename: Optional[str]
) -> Tuple[bytes, str, str]:
    if content_type == "application/pdf":
        pdf_bytes = data
        text = _pdf_to_text(pdf_bytes)
        return pdf_bytes, text, "pdf"

    if content_type == "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
        text = _docx_to_text(data)
        pdf_bytes = _text_to_pdf_bytes(text)
        return pdf_bytes, text, "docx"

    if content_type in ("text/plain", "text/csv"):
        text = _decode_text(data)
        pdf_bytes = _text_to_pdf_bytes(text)
        return pdf_bytes, text, "text"

    if content_type.startswith("image/"):
        pdf_bytes = _image_to_pdf_bytes(data)
        text = _image_to_text_via_vision(data, content_type)
        return pdf_bytes, text, "image"

    # Fallback by extension if content_type is missing
    if filename:
        guessed = mimetypes.guess_type(filename)[0] or ""
        if guessed and guessed != content_type:
            return _convert_to_pdf_and_text(data, guessed, filename)

    raise HTTPException(status_code=400, detail=f"Unsupported file type: {content_type}")


@router.post("/upload")
async def upload_document(
    file: UploadFile = File(..., description="Document to upload (pdf, docx, txt, csv, image)"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Upload a document, convert it to PDF, extract text, and upsert into Pinecone.
    """
    content_type = file.content_type or ""
    if content_type and content_type not in ALLOWED_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid file type: {content_type}. Allowed: {', '.join(sorted(ALLOWED_TYPES))}",
        )

    data = await file.read()
    size_mb = len(data) / (1024 * 1024)
    if size_mb > MAX_UPLOAD_MB:
        raise HTTPException(
            status_code=400,
            detail=f"File too large: {size_mb:.1f} MB. Max size: {MAX_UPLOAD_MB} MB.",
        )

    content_type = content_type or (mimetypes.guess_type(file.filename or "")[0] or "")
    pdf_bytes, text, source_type = _convert_to_pdf_and_text(data, content_type, file.filename)

    if not text.strip():
        raise HTTPException(
            status_code=400,
            detail="No extractable text found in the document.",
        )
    if not settings.OPENAI_API_KEY:
        raise HTTPException(
            status_code=503,
            detail="OPENAI_API_KEY is required to generate embeddings.",
        )

    pc = _require_pinecone()
    index = pc.Index(settings.PINECONE_INDEX_NAME)

    embeddings = OpenAIEmbeddings(
        model="text-embedding-3-small",
        api_key=settings.OPENAI_API_KEY,
        dimensions=settings.PINECONE_EMBEDDING_DIM,
    )
    splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=200)
    chunks = splitter.split_text(text)
    if not chunks:
        raise HTTPException(status_code=400, detail="Document has no text to index.")

    doc_id = uuid4().hex
    sha256 = hashlib.sha256(pdf_bytes).hexdigest()
    pdf_b64: Optional[str] = None

    vectors = []
    for i, chunk in enumerate(chunks):
        vector = embeddings.embed_query(chunk)
        metadata = {
            "doc_id": doc_id,
            "chunk_index": i,
            "filename": file.filename,
            "content_type": content_type,
            "source_type": source_type,
            "text_len": len(chunk),
            "text": chunk,
            "pdf_sha256": sha256,
            "pdf_stored": False,
            "uploader_email": current_user.email,
        }
        if i == 0:
            metadata["chunk_count"] = len(chunks)
        vectors.append({"id": f"{doc_id}-{i}", "values": vector, "metadata": metadata})

    namespace = settings.PINECONE_NAMESPACE or "documents"
    index.upsert(vectors=vectors, namespace=namespace)

    doc = DocumentModel(
        id=doc_id,
        filename=file.filename,
        content_type=content_type,
        source_type=source_type,
        chunk_count=len(vectors),
        uploader_id=current_user.id,
        uploader_email=current_user.email,
        pdf_sha256=sha256,
    )
    db.add(doc)
    db.commit()
    log_audit(
        db,
        actor=current_user,
        action="created",
        entity_type="document",
        entity_id=doc_id,
        status="indexed",
        source="api",
        description=f"Document uploaded: {file.filename}",
    )

    return {
        "message": "Document uploaded and indexed.",
        "doc_id": doc_id,
        "filename": file.filename,
        "chunks_indexed": len(vectors),
        "namespace": namespace,
        "pdf_sha256": sha256,
        "pdf_stored_in_pinecone": False,
    }


@router.get("/docs")
async def list_documents(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    List uploaded documents for the current user.
    """
    docs = (
        db.query(DocumentModel)
        .filter(DocumentModel.uploader_id == current_user.id)
        .order_by(DocumentModel.created_at.desc())
        .all()
    )
    return {
        "documents": [
            {
                "doc_id": d.id,
                "filename": d.filename,
                "content_type": d.content_type,
                "source_type": d.source_type,
                "chunk_count": d.chunk_count,
                "pdf_sha256": d.pdf_sha256,
                "created_at": d.created_at.isoformat() if d.created_at else None,
            }
            for d in docs
        ]
    }


@router.get("/docs/{doc_id}")
async def get_document_text(
    doc_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Return the full document text (reconstructed from Pinecone chunks) for a given doc_id.
    The frontend should pass the doc_id returned by /pinecone/upload.
    """
    try:
        pc = _require_pinecone()
        index = pc.Index(settings.PINECONE_INDEX_NAME)
        namespace = settings.PINECONE_NAMESPACE or "documents"

        doc = db.query(DocumentModel).filter(DocumentModel.id == doc_id).first()
        if not doc:
            raise HTTPException(status_code=404, detail="Document not found.")
        if doc.uploader_id != current_user.id:
            raise HTTPException(status_code=403, detail="You do not have access to this document.")
        chunk_count = doc.chunk_count
        if not isinstance(chunk_count, int) or chunk_count <= 0:
            raise HTTPException(
                status_code=400,
                detail="Document is missing chunk_count. Re-upload the document.",
            )

        ids = [f"{doc_id}-{i}" for i in range(chunk_count)]
        try:
            fetched = index.fetch(ids=ids, namespace=namespace)
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"Pinecone fetch error: {str(e)}")
        fetched_vectors = getattr(fetched, "vectors", None) or {}
        if not fetched_vectors:
            raise HTTPException(
                status_code=502,
                detail=f"Pinecone returned no vectors for doc_id={doc_id} namespace={namespace} chunk_count={chunk_count}",
            )
        chunks_with_index = []

        for _id, vec in fetched_vectors.items():
            meta = getattr(vec, "metadata", None) or {}
            text = meta.get("text") or ""
            idx = meta.get("chunk_index")
            idx_int: Optional[int] = None
            if isinstance(idx, int):
                idx_int = idx
            elif isinstance(idx, float):
                idx_int = int(idx)
            elif isinstance(idx, str) and idx.isdigit():
                idx_int = int(idx)
            if idx_int is not None:
                chunks_with_index.append((idx_int, text))

        if not chunks_with_index:
            raise HTTPException(
                status_code=500,
                detail=f"No text found for this document. fetched={len(fetched_vectors)}",
            )

        chunks_with_index.sort(key=lambda x: x[0])
        full_text = "\n".join([t for _, t in chunks_with_index]).strip()

        return {
            "doc_id": doc_id,
            "filename": doc.filename,
            "chunk_count": chunk_count,
            "text": full_text,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Document fetch error: {str(e)}")


@router.delete("/docs/{doc_id}")
async def delete_document(
    doc_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Delete a document: remove its vectors from Pinecone and remove DB record.
    """
    doc = db.query(DocumentModel).filter(DocumentModel.id == doc_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found.")
    if doc.uploader_id != current_user.id:
        raise HTTPException(status_code=403, detail="You do not have access to this document.")

    pc = _require_pinecone()
    index = pc.Index(settings.PINECONE_INDEX_NAME)
    namespace = settings.PINECONE_NAMESPACE or "documents"

    chunk_count = doc.chunk_count
    batch_size = 100
    for start in range(0, chunk_count, batch_size):
        ids = [f"{doc_id}-{i}" for i in range(start, min(start + batch_size, chunk_count))]
        index.delete(ids=ids, namespace=namespace)

    db.delete(doc)
    db.commit()
    log_audit(
        db,
        actor=current_user,
        action="deleted",
        entity_type="document",
        entity_id=doc_id,
        status="deleted",
        source="api",
        description=f"Document deleted: {doc.filename}",
    )

    return {"message": "Document deleted.", "doc_id": doc_id}
