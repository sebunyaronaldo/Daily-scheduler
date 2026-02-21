import os
import glob
from google.cloud import storage

# Write credentials to a temp file and point SDK to it
os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = "gcp-key.json"

bucket_name = os.environ.get("GCP_BUCKET_NAME")

if not bucket_name:
    print("❌ GCP_BUCKET_NAME environment variable not set")
    exit(1)

client = storage.Client()
bucket = client.bucket(bucket_name)

# Find the generated CSV file
csv_files = glob.glob("egp_contracts_webapp_ready_*.csv")

if csv_files:
    filename = csv_files[0]
    blob = bucket.blob(filename)
    blob.upload_from_filename(filename)
    print(f"✅ Uploaded {filename} to GCS bucket: {bucket_name}")
else:
    print("❌ No CSV file found to upload")
    exit(1)
```

---

**File 3: `requirements.txt`** (make sure it includes these):
```
requests
pandas
beautifulsoup4
google-cloud-storage
