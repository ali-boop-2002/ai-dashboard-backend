from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional

class Settings(BaseSettings):
    DATABASE_URL: str
    ENV: str = "dev"
    
    # Supabase Auth
    SUPABASE_URL: str
    SUPABASE_JWT_SECRET: str

    # OpenAI (for ChatGPT Vision / LangChain)
    OPENAI_API_KEY: Optional[str] = None

    # Pinecone
    PINECONE_API_KEY: Optional[str] = None
    PINECONE_INDEX_NAME: Optional[str] = None
    PINECONE_NAMESPACE: Optional[str] = None
    PINECONE_EMBEDDING_DIM: int = 512

    # Google Sheets
    GOOGLE_SHEETS_CREDENTIALS_FILE: str = "google-credentials.json"
    GOOGLE_SHEETS_SPREADSHEET_ID: str = "1DcSCddZxIic8c6AOfkrgwJWOPpjAqY0R7TQMgHgBeJ0"
    GOOGLE_SHEETS_WORKSHEET_NAME: str = "Sheet1"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

settings = Settings()
