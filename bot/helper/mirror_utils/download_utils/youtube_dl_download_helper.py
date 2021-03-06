from .download_helper import DownloadHelper
import time
from youtube_dl import YoutubeDL, DownloadError
import threading
from bot import LOGGER, download_dict_lock, download_dict, DOWNLOAD_DIR
from ..status_utils.youtube_dl_download_status import YoutubeDLDownloadStatus
import logging
import re

LOGGER = logging.getLogger(__name__)


class MyLogger:
    def __init__(self, obj):
        self.obj = obj

    def debug(self, msg):
        LOGGER.debug(msg)
        # Hack to fix changing changing extension
        match = re.search(r'.ffmpeg..Merging formats into..(.*?).$', msg)
        if match and not self.obj.is_playlist:
            self.obj.name = match.group(1)

    def warning(self, msg):
        LOGGER.warning(msg)

    def error(self, msg):
        LOGGER.error(msg)
        #self.obj.onDownloadError(msg)


class YoutubeDLHelper(DownloadHelper):
    def __init__(self, listener):
        super().__init__()
        self.__name = ""
        self.__start_time = time.time()
        self.__listener = listener
        self.__gid = ""
        self.opts = {
            'format': 'bestaudio/best',
            'progress_hooks': [self.__onDownloadProgress],
            'usenetrc': True,
            'format': "best"
        }
        self.ydl = YoutubeDL(self.opts)
        self.__download_speed = 0
        self.download_speed_readable = ''
        self.downloaded_bytes = 0
        self.size = 0
        self.is_playlist = False
        self.last_downloaded = 0
        self.is_cancelled = False
        self.vid_id = ''
        self.__resource_lock = threading.RLock()

    @property
    def download_speed(self):
        with self.__resource_lock:
            return self.__download_speed

    @property
    def gid(self):
        with self.__resource_lock:
            return self.__gid

    def __onDownloadProgress(self, d):
        if self.is_cancelled:
            raise ValueError("Cancelling Download..")
        if d['status'] == "finished":
            if self.is_playlist:
                self.last_downloaded = 0
        elif d['status'] == "downloading":
            with self.__resource_lock:
                self.__download_speed = d['speed']
                if self.is_playlist:
                    progress = d['downloaded_bytes'] / d['total_bytes']
                    chunk_size = d['downloaded_bytes'] - self.last_downloaded
                    self.last_downloaded = d['total_bytes'] * progress
                    self.downloaded_bytes += chunk_size
                    self.progress = (self.downloaded_bytes / self.size) * 100
                else:
                    self.download_speed_readable = d['_speed_str']
                    self.downloaded_bytes = d['downloaded_bytes']

    def __onDownloadStart(self):
        with download_dict_lock:
            download_dict[self.__listener.uid] = YoutubeDLDownloadStatus(self, self.__listener.uid)

    def __onDownloadComplete(self):
        self.__listener.onDownloadComplete()

    def onDownloadError(self, error):
        self.__listener.onDownloadError(error)

    def extractMetaData(self, link):
        result = self.ydl.extract_info(link, download=False)
        if result.get('direct'):
            return None
        if 'entries' in result:
            video = result['entries'][0]
            for v in result['entries']:
                if v.get('filesize'):
                    self.size += float(v['filesize'])
            self.name = video.get('playlist_title')
            self.vid_id = video.get('id')
            self.is_playlist = True
        else:
            video = result
            if video.get('filesize'):
                self.size = int(video.get('filesize'))
            self.name = f"{video.get('title')}.{video.get('ext')}"
            self.vid_id = video.get('id')
        return video

    def __download(self, link):
        try:
            self.ydl.download([link], )
            with YoutubeDL(self.opts) as ydl:
                try:
                    ydl.download([link])
                except DownloadError as e:
                    self.onDownloadError(str(e))
                    return
            self.__onDownloadComplete()
        except ValueError:
            LOGGER.info("Download Cancelled by User!")
            self.onDownloadError("Download Cancelled by User!")

    def add_download(self, link, path):
        LOGGER.info(f"Downloading with YT-DL: {link}")
        self.__gid = f"{self.vid_id}{self.__listener.uid}"
        self.opts['logger'] = MyLogger(self)
        if not self.is_playlist:
            self.opts['outtmpl'] = f"{path}/%(title)s.%(ext)s"
        else:
            self.opts['outtmpl'] = f"{path}/%(playlist_title)s/%(title)s.%(ext)s"
        self.ydl = YoutubeDL(self.opts)
        self.__onDownloadStart()
        threading.Thread(target=self.__download, args=(link,)).start()

    def cancel_download(self):
        self.is_cancelled = True
