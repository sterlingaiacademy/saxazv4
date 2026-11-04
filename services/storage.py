import os
import shutil
import uuid
from typing import Optional
from fastapi import UploadFile

try:
    from google.cloud import storage as gcs_storage
except ImportError:
    gcs_storage = None

# Use /data/media in Cloud Run (which is mounted to the GCS bucket via FUSE)
if os.environ.get("K_SERVICE"):
    LOCAL_MEDIA_BASE = "/data/media"
else:
    LOCAL_MEDIA_BASE = "media"

def upload_file(file: UploadFile, directory: str) -> Optional[str]:
    """
    Uploads a file. If GCS_RESOURCES_BUCKET is set, it uploads directly to GCS.
    Otherwise, it uploads to the local media directory (which may be a FUSE mount).
    """
    if not file or not file.filename:
        return None

    ext = os.path.splitext(file.filename)[1]
    ALLOWED_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.gif', '.webp', '.mp4', '.mp3', '.wav', '.ogg', '.pdf', '.doc', '.docx', '.xlsx', '.pptx'}
    if ext.lower() not in ALLOWED_EXTENSIONS:
        raise ValueError(f"File type '{ext}' is not allowed")
    unique_name = f"{uuid.uuid4()}{ext}"
    
    gcs_bucket_name = os.environ.get("GCS_RESOURCES_BUCKET")
    
    # Try GCS native upload first
    if gcs_bucket_name and gcs_storage:
        try:
            client = gcs_storage.Client()
            bucket = client.bucket(gcs_bucket_name)
            blob = bucket.blob(f"{directory.strip('/')}/{unique_name}")
            
            file.file.seek(0)
            blob.upload_from_file(file.file, content_type=file.content_type)
            
            # Since the bucket might have uniform bucket-level access, 
            # make_public() might fail, but public_url will still return the URL.
            try:
                blob.make_public()
            except Exception:
                pass 
                
            return blob.public_url
        except Exception as e:
            print(f"CRITICAL: GCS Native Upload failed: {e}")
            # If they configured GCS but it fails (e.g., IAM permission issue), 
            # we MUST fail loudly. Silently falling back to ephemeral local storage 
            # in Cloud Run causes disappearing files.
            raise e
            
    # Local/FUSE Storage Fallback (Only if GCS_RESOURCES_BUCKET is NOT set)
    upload_dir = os.path.join(LOCAL_MEDIA_BASE, directory.strip('/'))
    os.makedirs(upload_dir, exist_ok=True)
    file_path = os.path.join(upload_dir, unique_name)
    
    file.file.seek(0)
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
        
    return f"/media/{directory.strip('/')}/{unique_name}"

def append_chunk(file_id: str, chunk_data: bytes):
    """
    Appends a binary chunk to a temporary file on local disk.
    Used for bypassing Cloud Run's 32MB request limits.
    """
    import re
    if not file_id or not re.match(r'^[a-zA-Z0-9_-]+$', file_id):
        raise ValueError("Invalid file ID")

    tmp_dir = os.path.join(LOCAL_MEDIA_BASE, "tmp")
    os.makedirs(tmp_dir, exist_ok=True)
    file_path = os.path.join(tmp_dir, f"{file_id}.part")

    with open(file_path, "ab") as f:
        f.write(chunk_data)

class _DummyUploadFile:
    def __init__(self, filename, file_obj, content_type):
        self.filename = filename
        self.file = file_obj
        self.content_type = content_type

def finalize_chunked_upload(file_id: str, original_filename: str, directory: str) -> Optional[str]:
    """
    Takes the fully assembled temporary file and processes it through the normal upload_file pipeline.
    """
    import re
    if not file_id or not re.match(r'^[a-zA-Z0-9_-]+$', file_id):
        raise ValueError("Invalid file ID")

    tmp_dir = os.path.join(LOCAL_MEDIA_BASE, "tmp")
    file_path = os.path.join(tmp_dir, f"{file_id}.part")
    
    if not os.path.exists(file_path):
        return None
        
    ext = os.path.splitext(original_filename)[1].lower()
    content_type = "video/mp4"
    if ext == ".pdf": content_type = "application/pdf"
    elif ext in [".png", ".jpg", ".jpeg", ".webp", ".gif"]: content_type = "image/jpeg"
    elif ext in [".mp3", ".wav", ".ogg"]: content_type = "audio/mpeg"
    elif ext in [".doc", ".docx"]: content_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    
    try:
        with open(file_path, "rb") as f:
            dummy_file = _DummyUploadFile(original_filename, f, content_type)
            media_url = upload_file(dummy_file, directory)
    finally:
        try:
            if os.path.exists(file_path):
                os.remove(file_path)
        except Exception:
            pass
        
    return media_url

def delete_file(media_url: str) -> bool:
    """
    Deletes a file from GCS (if GCS_RESOURCES_BUCKET is set) or from local storage.
    Returns True if deleted, False if not found or on error.
    """
    if not media_url:
        return False

    gcs_bucket_name = os.environ.get("GCS_RESOURCES_BUCKET")

    if gcs_bucket_name and gcs_storage and media_url.startswith("https://"):
        try:
            client = gcs_storage.Client()
            bucket = client.bucket(gcs_bucket_name)
            # Extract blob path from public URL
            # e.g. https://storage.googleapis.com/bucket-name/path/to/file.ext
            prefix = f"https://storage.googleapis.com/{gcs_bucket_name}/"
            if media_url.startswith(prefix):
                blob_name = media_url[len(prefix):]
                blob = bucket.blob(blob_name)
                blob.delete()
                return True
        except Exception as e:
            print(f"Warning: Could not delete GCS file '{media_url}': {e}")
            return False
    elif media_url.startswith("/media/"):
        # Local storage path
        base_abs = os.path.abspath(LOCAL_MEDIA_BASE)
        local_path = os.path.abspath(os.path.join(LOCAL_MEDIA_BASE, media_url[len("/media/"):]))
        # Prevent path traversal
        try:
            if os.path.commonpath([local_path, base_abs]) != base_abs:
                print(f"Warning: Path traversal attempt blocked: {media_url}")
                return False
        except ValueError:
            return False
        if os.path.exists(local_path):
            try:
                os.remove(local_path)
                return True
            except Exception as e:
                print(f"Warning: Could not delete local file '{local_path}': {e}")
    return False
