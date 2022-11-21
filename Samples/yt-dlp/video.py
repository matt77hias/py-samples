import yt_dlp

urls = ['']

ydl_opts = {
    'format_sort': ['ext:mp4:m4a']
}

with yt_dlp.YoutubeDL(ydl_opts) as ydl:
    error_code = ydl.download(urls)
