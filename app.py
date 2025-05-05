import os
import re
import datetime
import subprocess
import requests
from flask import Flask, request, jsonify

# Setup
app = Flask(__name__)
PDF_DIR = os.getenv('PDF_DIR', '/app/pdfs')
RM_USER = os.getenv('REMARKABLE_USER')
RM_PASS = os.getenv('REMARKABLE_PASS')
RM_DIR = os.getenv('RM_TARGET_DIR', '/')

# Helpers
def download_pdf(url):
    """
    Download a PDF from the given URL with custom headers to mimic a real browser.
    """
    os.makedirs(PDF_DIR, exist_ok=True)
    local_name = url.split('/')[-1]
    local_path = os.path.join(PDF_DIR, local_name)

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/113.0.0.0 Safari/537.36"
        )
    }

    r = requests.get(url, headers=headers)
    r.raise_for_status()
    with open(local_path, 'wb') as f:
        f.write(r.content)

    return local_path

def rename_and_upload(path):
    today = datetime.date.today()
    new_name = today.strftime("%B %-d %Y") + ".pdf"
    new_path = os.path.join(PDF_DIR, new_name)
    os.rename(path, new_path)
    # subprocess.run(["rmapi", "login", "--username", RM_USER, "--password", RM_PASS], check=True)
    subprocess.run(["rmapi", "put", new_path, RM_DIR], check=True)
    return new_path

def cleanup_old():
    """
    Remove files in RM_DIR whose names are exactly "Month D YYYY" and older than 7 days.
    """
    import datetime, subprocess, os

    today = datetime.date.today()
    cutoff = today - datetime.timedelta(days=7)

    proc = subprocess.run(
        ["rmapi", "ls", RM_DIR],
        capture_output=True, text=True, check=True
    )
    lines = proc.stdout.splitlines()

    for line in lines:
        parts = line.split()
        if not parts or parts[0] != "[f]":
            continue

        # join _all_ tokens after "[f]" to reconstruct the full filename
        filename = " ".join(parts[1:])  # e.g. "May 5 2025"

        try:
            file_date = datetime.datetime.strptime(filename, "%B %d %Y").date()
        except ValueError:
            # filename isn’t exactly Month D YYYY → skip
            continue

        if file_date < cutoff:
            remote_path = os.path.join(RM_DIR, filename)
            print(f"Removing {remote_path} (dated {file_date})")
            subprocess.run(["rmapi", "rm", remote_path], check=True)


# Webhook endpoint
@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.json or {}
    text = data.get('text', '')
    # extract the first URL
    match = re.search(r'https?://[^\s]+', text)
    if not match:
        return jsonify({'status': 'error', 'message': 'No URL found in message'}), 400

    url = match.group(0)
    try:
        local_path = download_pdf(url)
        uploaded = rename_and_upload(local_path)
        cleanup_old()
        return jsonify({'status': 'ok', 'uploaded': uploaded})
        # return jsonify({'status': 'ok'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8000)
