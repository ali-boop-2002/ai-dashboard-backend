# Frontend: How to Use the AI Scan Data API

This doc explains how the frontend can call **POST /ai/scan-data** (image upload + ChatGPT Vision) and what happens when the user sends text instead of an image.

---

## 1. Endpoint summary

| Item | Value |
|------|--------|
| **URL** | `POST {API_BASE_URL}/ai/scan-data` |
| **Auth** | Required. Send Supabase JWT in `Authorization: Bearer <access_token>` |
| **Body** | `multipart/form-data` with an image file and optional text prompt |
| **Who can call** | Only users with **admin** role (others get 403) |

**Example base URLs:**
- Local: `http://localhost:8000`
- Production: `https://your-backend.herokuapp.com`

Full URL example: `http://localhost:8000/ai/scan-data`

---

## 2. Request format

### Headers

- **Authorization** (required): `Bearer <supabase_access_token>`
- **Content-Type**: Do **not** set this yourself. The browser sets it to `multipart/form-data; boundary=...` when you use `FormData`.

### Body (multipart/form-data)

| Field   | Type | Required | Description |
|--------|------|----------|-------------|
| `image` | File | Yes      | Image file. Allowed: JPEG, PNG, GIF, WebP. Max 10 MB. |
| `prompt` | String | No   | Optional instruction for the AI (e.g. "Extract all numbers"). If omitted, backend uses a default analysis prompt. |

---

## 3. Example: fetch with FormData

```typescript
import { supabase } from './supabase'; // or wherever your client lives

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000';

async function scanImage(file: File, prompt?: string): Promise<{ analysis: string }> {
  const { data: { session } } = await supabase.auth.getSession();
  if (!session?.access_token) {
    throw new Error('Not authenticated');
  }

  const formData = new FormData();
  formData.append('image', file);           // required: the image file
  if (prompt?.trim()) {
    formData.append('prompt', prompt.trim()); // optional: custom instruction
  }

  const response = await fetch(`${API_BASE_URL}/ai/scan-data`, {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${session.access_token}`,
      // Do NOT set Content-Type; browser sets multipart/form-data + boundary
    },
    body: formData,
  });

  if (!response.ok) {
    const err = await response.json().catch(() => ({ detail: response.statusText }));
    throw new Error(err.detail ?? `Request failed: ${response.status}`);
  }

  const data = await response.json();
  return { analysis: data.analysis, message: data.message, prompt_used: data.prompt_used };
}
```

**Usage in a form / file input:**

```tsx
// Example: file input + optional textarea for prompt
function ScanDataForm() {
  const [file, setFile] = useState<File | null>(null);
  const [prompt, setPrompt] = useState('');
  const [result, setResult] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!file) {
      setError('Please select an image.');
      return;
    }
    setError(null);
    setLoading(true);
    try {
      const { analysis } = await scanImage(file, prompt || undefined);
      setResult(analysis);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Upload failed');
    } finally {
      setLoading(false);
    }
  };

  return (
    <form onSubmit={handleSubmit}>
      <input
        type="file"
        accept="image/jpeg,image/png,image/gif,image/webp"
        onChange={(e) => setFile(e.target.files?.[0] ?? null)}
      />
      <textarea
        placeholder="Optional: e.g. Extract all numbers"
        value={prompt}
        onChange={(e) => setPrompt(e.target.value)}
      />
      <button type="submit" disabled={loading}>Scan image</button>
      {error && <p className="error">{error}</p>}
      {result && <pre>{result}</pre>}
    </form>
  );
}
```

---

## 4. Response shape

**Success (200 OK):**

```json
{
  "message": "Data scanned successfully",
  "analysis": "The AI's text description of the image...",
  "prompt_used": "Analyze this image in detail. Describe what you see..."
}
```

- **`analysis`**: Use this in the UI (e.g. show in a modal or a “results” section).
- **`prompt_used`**: The prompt that was actually sent (default or user’s).

---

## 5. Error responses (what to show the user)

| Status | Meaning | Typical `detail` | Frontend suggestion |
|--------|--------|-------------------|---------------------|
| **400** | Bad request (wrong file type or too big) | e.g. `Invalid file type: text/plain. Allowed: image/jpeg, image/png, image/gif, image/webp` or `Image too large: 12.0 MB. Max size: 10 MB.` | Show `detail` and ask user to pick an image (JPEG/PNG/GIF/WebP, max 10 MB). |
| **401** | Not logged in or invalid/expired token | `Invalid authentication credentials` (or similar) | Redirect to login or refresh session. |
| **403** | Not admin | `Forbidden. Admin role required.` | Show “Admin only” message and hide or disable the feature for non-admins. |
| **502** | Vision API error (e.g. OpenAI failure) | `Vision API error: ...` | Show “Analysis failed, try again” and optionally `detail`. |
| **503** | Backend not configured for Vision | `OpenAI API key is not configured...` | Show “Image analysis is temporarily unavailable.” |

Parse once and show one message:

```typescript
const data = await response.json().catch(() => ({}));
const message = data.detail ?? response.statusText;
// then show `message` in your UI
```

---

## 6. What if the user sends text instead of an image?

If the user selects a **text file** (or any non-image file) and the frontend sends it in the `image` field:

- The backend looks at the file’s **Content-Type** (e.g. `text/plain` for a .txt file).
- It only allows: `image/jpeg`, `image/png`, `image/gif`, `image/webp`.
- So the request is rejected with **400 Bad Request** and a body like:

  ```json
  {
    "detail": "Invalid file type: text/plain. Allowed: image/jpeg, image/png, image/gif, image/webp"
  }
  ```

So: **the backend never runs Vision on a text file.** The user gets a clear error; you can show `detail` and ask them to choose an image.

To reduce mistakes on the frontend:

- Use `accept="image/jpeg,image/png,image/gif,image/webp"` on the file input so the file picker suggests only images.
- Optionally check `file.type` before calling the API and show a friendly message if it’s not an image:

  ```typescript
  const allowed = ['image/jpeg', 'image/png', 'image/gif', 'image/webp'];
  if (!file || !allowed.includes(file.type)) {
    setError('Please select an image (JPEG, PNG, GIF, or WebP).');
    return;
  }
  ```

---

## 7. Checklist for integration

1. Use **POST** to `{API_BASE_URL}/ai/scan-data`.
2. Set **Authorization: Bearer &lt;supabase_access_token&gt;** (from `supabase.auth.getSession()`).
3. Send **FormData** with:
   - `image`: the image **File** (required).
   - `prompt`: optional string.
4. Do **not** set `Content-Type` when sending `FormData` (let the browser set it).
5. Only **admins** can call this; show “Admin only” or hide the feature for others.
6. Handle **400** (wrong file type / too big) and show the `detail` message when the user sends text or a non-image file.
