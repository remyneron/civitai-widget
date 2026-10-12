import os
import json
import time
import requests
from PySide6.QtCore import QThread, Signal, QObject

CACHE_DIR = os.path.expanduser("~/.cache/civitai_widget")
METADATA_CACHE_DURATION = 3600  # 1 hour in seconds

class DownloadWorker(QThread):
    # Signals to communicate with the GUI thread
    image_downloaded = Signal(str, str)  # image_id, local_path
    download_failed = Signal(str, str)   # image_id, error_msg

    def __init__(self, download_queue):
        super().__init__()
        self.queue = download_queue
        self.running = True

    def run(self):
        # Setup headers to look like a standard client
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        
        while self.running:
            try:
                # Get a download task from the queue
                # block=True with timeout allows checking self.running periodically
                item = self.queue.get(timeout=1.0)
            except Exception:
                continue

            if item is None:  # Sentinel to stop
                break

            image_id, url, local_path = item
            
            try:
                # Check if it was already downloaded by another thread or process
                if os.path.exists(local_path) and os.path.getsize(local_path) > 0:
                    self.image_downloaded.emit(image_id, local_path)
                    self.queue.task_done()
                    continue
                
                # Fetch image data
                response = requests.get(url, headers=headers, timeout=15)
                if response.status_code == 200:
                    # Write to a temporary file first, then rename to make it atomic
                    temp_path = local_path + ".tmp"
                    with open(temp_path, "wb") as f:
                        f.write(response.content)
                    os.rename(temp_path, local_path)
                    self.image_downloaded.emit(image_id, local_path)
                else:
                    self.download_failed.emit(image_id, f"HTTP {response.status_code}")
            except Exception as e:
                self.download_failed.emit(image_id, str(e))
            finally:
                self.queue.task_done()

    def stop(self):
        self.running = False


class MetadataFetcher(QThread):
    metadata_loaded = Signal(list, str)  # items list, next_cursor
    load_failed = Signal(str)

    def __init__(self, nsfw, cache_dir, metadata_file, cursor=None):
        super().__init__()
        self.nsfw = nsfw
        self.cache_dir = cache_dir
        self.metadata_file = metadata_file
        self.cursor = cursor

    def run(self):
        url = "https://civitai.com/api/v1/images"
        params = {
            "sort": "Most Reactions",
            "period": "Week",
            "limit": 100,
            "nsfw": "true" if self.nsfw else "false"
        }
        if self.cursor:
            params["cursor"] = self.cursor
            
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        try:
            response = requests.get(url, params=params, headers=headers, timeout=15)
            if response.status_code == 200:
                data = response.json()
                items = data.get("items", [])
                
                # Filter to only type "image" and valid URLs
                valid_items = [item for item in items if item.get("type") == "image" and item.get("url")]
                top_60 = valid_items[:60]
                
                next_cursor = data.get("metadata", {}).get("nextCursor", "")
                
                # Only save to cache for the first page
                if not self.cursor:
                    with open(self.metadata_file, "w") as f:
                        json.dump(top_60, f)
                
                self.metadata_loaded.emit(top_60, next_cursor)
            else:
                self.load_failed.emit(f"Civitai API HTTP {response.status_code}")
        except Exception as e:
            # Try loading expired cache as fallback (only for first page)
            if not self.cursor and os.path.exists(self.metadata_file):
                try:
                    with open(self.metadata_file, "r") as f:
                        items = json.load(f)
                        self.metadata_loaded.emit(items[:60], "")
                        return
                except Exception:
                    pass
            self.load_failed.emit(str(e))


class CivitaiManager(QObject):
    image_ready = Signal(str, str)  # image_id, filepath
    metadata_loaded = Signal(list, str)  # items list, next_cursor
    load_failed = Signal(str)       # error message

    def __init__(self):
        super().__init__()
        self.cache_dir = CACHE_DIR
        os.makedirs(self.cache_dir, exist_ok=True)
        
        # Download queue and worker thread
        from queue import Queue
        self.download_queue = Queue()
        self.worker = DownloadWorker(self.download_queue)
        self.worker.image_downloaded.connect(self._on_image_downloaded)
        self.worker.download_failed.connect(self._on_download_failed)
        self.worker.start()
        
        self.fetcher = None

    def fetch_top_images(self, nsfw=False, force_refresh=False, cursor=None):
        """
        Fetches top 60 images. Uses cached metadata if available and fresh.
        """
        mode = "nsfw" if nsfw else "sfw"
        metadata_file = os.path.join(self.cache_dir, f"metadata_{mode}.json")
        
        # Check cache (first page only)
        if not cursor and not force_refresh and os.path.exists(metadata_file):
            mtime = os.path.getmtime(metadata_file)
            if time.time() - mtime < METADATA_CACHE_DURATION:
                try:
                    with open(metadata_file, "r") as f:
                        items = json.load(f)
                        if len(items) >= 60:
                            self.metadata_loaded.emit(items[:60], "")
                            return
                except Exception:
                    pass

        # Stop existing fetcher if running
        if self.fetcher and self.fetcher.isRunning():
            self.fetcher.terminate()
            self.fetcher.wait()
            
        # Start new fetcher
        self.fetcher = MetadataFetcher(nsfw, self.cache_dir, metadata_file, cursor)
        self.fetcher.metadata_loaded.connect(self.metadata_loaded.emit)
        self.fetcher.load_failed.connect(self.load_failed.emit)
        self.fetcher.start()

    def queue_image_download(self, image_id, url):
        """
        Queues an image for background download. Resolves thumbnail URL automatically.
        """
        # Optimize URL to request 450px wide thumbnail instead of original
        if "/original=true/" in url:
            opt_url = url.replace("/original=true/", "/width=450/")
        else:
            opt_url = url
            
        local_path = os.path.join(self.cache_dir, f"{image_id}_450.jpg")
        
        # If already cached, notify immediately
        if os.path.exists(local_path) and os.path.getsize(local_path) > 0:
            self.image_ready.emit(image_id, local_path)
        else:
            self.download_queue.put((image_id, opt_url, local_path))

    def _on_image_downloaded(self, image_id, path):
        self.image_ready.emit(image_id, path)

    def _on_download_failed(self, image_id, error_msg):
        # We can handle failures silently or log them
        print(f"Failed to download image {image_id}: {error_msg}")

    def clean_old_cache(self):
        """
        Deletes cached image files that are older than 1 week to save disk space.
        """
        now = time.time()
        for filename in os.listdir(self.cache_dir):
            filepath = os.path.join(self.cache_dir, filename)
            # Avoid deleting metadata caches
            if filename.startswith("metadata_"):
                continue
            if os.path.isfile(filepath):
                # 7 days limit
                if now - os.path.getmtime(filepath) > 7 * 86400:
                    try:
                        os.remove(filepath)
                    except Exception:
                        pass

    def stop_worker(self):
        self.worker.stop()
        self.worker.wait()
