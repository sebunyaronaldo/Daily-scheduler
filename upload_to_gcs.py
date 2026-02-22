import os
import glob
from google.cloud import storage

os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = "gcp-key.json"

bucket_name = "egp-contracts-data"

client = storage.Client()
bucket = client.bucket(bucket_name)

csv_files = glob.glob("egp_contracts_webapp_ready_*.csv")

if csv_files:
    filename = csv_files[0]
    blob = bucket.blob(filename)
    blob.upload_from_filename(filename)
    print("Uploaded " + filename + " to GCS bucket: " + bucket_name)
else:
    print("No CSV file found to upload")
    exit(1)
