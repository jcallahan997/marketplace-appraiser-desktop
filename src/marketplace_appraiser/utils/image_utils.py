"""Image download and processing utilities."""

import hashlib
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import urlparse

import requests


def download_image(url: str, output_dir: Path) -> Path:
    """Download an image from a URL and save it locally.

    Uses a hash of the URL as the filename to deduplicate downloads.

    Returns:
        Path to the saved image file.

    Raises:
        requests.RequestException: If the download fails.
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    # Determine file extension from URL or default to .jpg
    parsed = urlparse(url)
    path_ext = Path(parsed.path).suffix.lower()
    ext = path_ext if path_ext in (".jpg", ".jpeg", ".png", ".webp") else ".jpg"

    # Hash the URL for a stable, unique filename
    url_hash = hashlib.md5(url.encode()).hexdigest()[:12]
    filename = f"listing_{url_hash}{ext}"
    filepath = output_dir / filename

    if filepath.exists():
        return filepath

    response = requests.get(url, timeout=30)
    response.raise_for_status()
    filepath.write_bytes(response.content)

    return filepath


def download_images_parallel(
    urls: list[str], output_dir: Path, max_workers: int = 4
) -> list[str]:
    """Download multiple images in parallel using a thread pool.

    Returns list of successfully downloaded file paths (as strings).
    Failed downloads are logged and skipped.  Order matches the input URLs.
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        future_to_url = {
            pool.submit(download_image, url, output_dir): url
            for url in urls
        }
        url_to_path: dict[str, str] = {}
        for future in as_completed(future_to_url):
            url = future_to_url[future]
            try:
                path = future.result()
                url_to_path[url] = str(path)
            except Exception as e:
                print(f"  Warning: failed to download image: {e}")

    # Preserve original URL order
    paths: list[str] = []
    for url in urls:
        if url in url_to_path:
            paths.append(url_to_path[url])

    return paths
