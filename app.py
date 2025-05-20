import os
import re
import datetime
import subprocess
import requests
from flask import Flask, request, jsonify
import functools
import shutil
import calendar

print = functools.partial(print, flush=True)

# Setup
app = Flask(__name__)
PDF_DIR      = os.getenv('PDF_DIR', '/app/pdfs')
RM_USER      = os.getenv('REMARKABLE_USER')
RM_PASS      = os.getenv('REMARKABLE_PASS')
DEFAULT_RM_DIR  = os.getenv('RM_TARGET_DIR', '/')
GS_COMPAT    = '1.4'
GS_SETTINGS  = '/ebook'

# Helpers

def download_pdf(url, tmp=False, prefix=''):
    """
    Download a PDF from the given URL into either /tmp (if tmp=True)
    or into a folder under PDF_DIR matching prefix (if provided),
    and return the local path.
    """
    # Determine destination directory
    if tmp:
        dest_dir = '/tmp'
    else:
        # use prefix-named subfolder if prefix provided
        dest_dir = os.path.join(PDF_DIR, prefix) if prefix else PDF_DIR
    os.makedirs(dest_dir, exist_ok=True)

    local_name = url.split('/')[-1]
    local_path = os.path.join(dest_dir, local_name)

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

def cleanup_old(prefix='', rm_dir=DEFAULT_RM_DIR):
    """
    Use Ghostscript to compress the PDF at `path`. Returns the path to the compressed file.
    """
    base, ext = os.path.splitext(path)
    compressed_path = f"{base}_compressed{ext}"
    subprocess.run([
        "gs",
        "-sDEVICE=pdfwrite",
        f"-dCompatibilityLevel={GS_COMPAT}",
        f"-dPDFSETTINGS={GS_SETTINGS}",
        "-dNOPAUSE",
        "-dBATCH",
        f"-sOutputFile={compressed_path}",
        path
    ], check=True)
    return compressed_path

def compress_pdf(path):
    """
    Use Ghostscript to compress the PDF at `path`. Returns the path to the compressed file.
    """
    base, ext = os.path.splitext(path)
    compressed_path = f"{base}_compressed{ext}"
    subprocess.run([
        "gs",
        "-sDEVICE=pdfwrite",
        f"-dCompatibilityLevel={GS_COMPAT}",
        f"-dPDFSETTINGS={GS_SETTINGS}",
        "-dNOPAUSE",
        "-dBATCH",
        f"-sOutputFile={compressed_path}",
        path
    ], check=True)
    return compressed_path

def rename_and_upload(path, prefix='', rm_dir=DEFAULT_RM_DIR):
    """
    1) Move `path` into PDF_DIR as "<prefix> Month D.pdf"
    2) Upload that file via rmapi
    3) Rename the local copy to "<prefix> Month D YYYY.pdf"
    """

    target_dir = os.path.join(PDF_DIR, prefix) if prefix else PDF_DIR
    os.makedirs(target_dir, exist_ok=True)
    # 1. Build date strings
    today = datetime.date.today()
    month, day, year = today.strftime("%B"), str(today.day), str(today.year)

    # 2. Local no-year filename → move into target_dir
    no_year_name = f"{prefix} {month} {day}.pdf" if prefix else f"{month} {day}.pdf"
    no_year_path = os.path.join(target_dir, no_year_name)
    shutil.move(path, no_year_path)

    # 3. Upload the yearless file
    subprocess.run(
        ["rmapi", "put", no_year_path, rm_dir],
        check=True
    )

    # 4. Rename local file to include the year
    with_year_name = f"{prefix} {month} {day} {year}.pdf" if prefix else f"{month} {day} {year}.pdf"
    with_year_path = os.path.join(target_dir, with_year_name)
    os.rename(no_year_path, with_year_path)

    return with_year_path

def cleanup_old(prefix='', rm_dir=DEFAULT_RM_DIR):
    """
    Remove files in RM_DIR named "<prefix> Month D.pdf" older than 7 days,
    with detailed debug logs.
    """
    today  = datetime.date.today()
    cutoff = today - datetime.timedelta(days=7)
    print(f"[cleanup] today = {today}, cutoff = {cutoff}")

    # 1) list remote files
    proc = subprocess.run(
        ["rmapi", "ls", rm_dir],
        capture_output=True, text=True, check=True
    )
    lines = proc.stdout.splitlines()
    print(f"[cleanup] raw output ({len(lines)} lines):")
    for ln in lines:
        print("   ", repr(ln))
    print("-" * 60)

    # 2) process each line
    for idx, line in enumerate(lines):
        print(f"[cleanup] line {idx}: {repr(line)}")
        parts = line.split(None, 1)
        if len(parts) != 2 or parts[0] != '[f]':
            print("  ↳ skipping (not a file entry)")
            continue

        filename = parts[1]
        print(f"  ↳ filename = {filename!r}")

        # 3) strip .pdf **only if present**
        if filename.lower().endswith('.pdf'):
            base = filename[:-4]
            print(f"  ↳ removed '.pdf' → base = {base!r}")
        else:
            base = filename
            print(f"  ↳ no '.pdf' suffix → base = {base!r}")

        # 4) drop the prefix text
        if prefix:
            prefix_token = prefix + " "
            if not base.startswith(prefix_token):
                print(f"  ↳ skipping (doesn't start with prefix '{prefix}')")
                continue
            base = base[len(prefix_token):]
            print(f"  ↳ after dropping prefix → {base!r}")

        # 5) extract Month + Day via regex
        m = re.match(r"^([A-Za-z]+)\s+(\d+)$", base)
        if not m:
            print(f"  ↳ skipping (base not 'Month D' format) → {base!r}")
            continue
        month_str, day_str = m.groups()
        print(f"  ↳ month_str = {month_str}, day_str = {day_str}")

        # 6) parse into a date, inferring year
        try:
            month = list(calendar.month_name).index(month_str)
            day   = int(day_str)
        except ValueError as e:
            print(f"  ⚠️ parse error: {e}")
            continue

        file_date = datetime.date(today.year, month, day)
        if file_date > today:
            file_date = datetime.date(today.year - 1, month, day)
            print(f"  ↳ adjusted into last year → {file_date}")
        else:
            print(f"  ↳ parsed file_date = {file_date}")

        # 7) compare against cutoff
        if file_date < cutoff:
            remote_path = os.path.join(rm_dir, filename)
            print(f"  ↳ Removing {remote_path} (dated {file_date} < {cutoff})")
            subprocess.run(["rmapi", "rm", remote_path], check=True)
        else:
            print(f"  ↳ Keeping {filename} (dated {file_date} ≥ {cutoff})")


# Webhook endpoint
@app.route('/webhook', methods=['POST'])
def webhook():
    print(">>> Incoming request to /webhook")
    print("Request headers:", dict(request.headers))
    print("Request form data:", request.form)
    print("Request body:", request.data.decode('utf-8', errors='replace'))

    prefix       = request.form.get('prefix', '').strip()
    compress_str = request.form.get('compress', 'false').strip().lower()
    compress     = compress_str in ('true', '1', 'yes')

    text   = request.form.get('Body', '')
    sender = request.form.get('From')
    print(f"From: {sender}, Body: {text}")
    print(f"Prefix: '{prefix}', Compress: {compress}")

    manage_str = request.form.get('manage', 'false').strip().lower()
    manage     = manage_str in ('true', '1', 'yes')
    print(f"Manage: {manage!r}, Prefix: {prefix!r}, Compress: {compress}")

    archive_str  = request.form.get('archive', 'false').strip().lower()
    archive      = archive_str in ('true', '1', 'yes')
    print(f"Archive: {archive!r}")

    rm_dir_param = request.form.get('rm_dir', '').strip()
    rm_dir       = rm_dir_param or DEFAULT_RM_DIR

    match = re.search(r'https?://[^\s]+', text)
    if not match:
        print("❌ No URL found in message")
        return jsonify({'status': 'error', 'message': 'No URL found in message'}), 400


    # 1. Download
    local_path = download_pdf(match.group(0), tmp=not archive or compress, prefix=prefix)
    # local_path = download_pdf(match.group(0), tmp=compress, prefix=prefix)

    # 2. Optionally compress
    if compress:
        print("🔧 Compressing PDF via Ghostscript")
        local_path = compress_pdf(local_path)

    try:
        if manage:
            # 3a. If managing: do your prefix/rename logic (it uploads once, inside rename_and_upload)
            print("📤 Managed upload + rename …")
            uploaded = rename_and_upload(local_path, prefix, rm_dir)
            cleanup_old(prefix)
            print("✅ Managed upload successful:", uploaded)
        else:
            # 3b. If not managing: just one raw upload, no extra rename or cleanup
            print("📤 Simple upload (no rename/cleanup) …")
            subprocess.run(["rmapi", "put", local_path, rm_dir], check=True)
            uploaded = os.path.join(rm_dir, os.path.basename(local_path))
            print("ℹ️ Uploaded without rename/cleanup:", uploaded)

        return jsonify({'status': 'ok', 'uploaded': uploaded})

    except Exception as e:
        print(f"❌ Exception: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8000)
