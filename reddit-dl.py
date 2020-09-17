import logging.config
import os
import re
import requests
import subprocess
import sys

from dataclasses import dataclass
from dotenv import load_dotenv


@dataclass
class VideoPost:
  title: str
  postBaseUrl: str
  videoUrl: str
  hlsUrl: str
  audioUrl: str = ''

  def setAudioUrl(self, audioUrl: str) -> None:
    self.audioUrl = audioUrl


def extractMediaUri(hlsLine: str) -> (str, int):
  match = re.search(pattern='HLS_AUDIO_\\d+_K\\.m3u8', string=hlsLine).group()
  if not match:
    return '', 0
  return match, int(match.split('_')[2])


def writeContentToFile(url: str, fileName: str) -> None:
  log.info(f"Saving stream to '{fileName}'")
  with open(fileName, 'wb') as f:
    r = requests.get(url)
    f.write(r.content)
    log.info(f"Wrote {int(os.stat(fileName).st_size / 1024)} KB")


load_dotenv()
OAUTH_USER = os.getenv('OAUTH_USER')
OAUTH_SECRET = os.getenv('OAUTH_SECRET')
LOGLEVEL = os.getenv('LOGLEVEL') or 'INFO'
FFMPEG = os.getenv('FFMPEG') or 'ffmpeg'
USER_AGENT = os.getenv('USER_AGENT') or 'dumb_bot'

if LOGLEVEL != 'OFF':
  logging.config.dictConfig(
    dict(
      version=1,
      disable_existing_loggers=True,
      formatters={
        'f': {'format': '%(levelname)-5s %(asctime)s  %(message)s'}
      },
      handlers={
        'console': {
          'class': 'logging.StreamHandler',
          'formatter': 'f',
          'level': LOGLEVEL,
        },
      },
      root={
        'handlers': ['console'],
        'level': LOGLEVEL,
      },
    )
  )
log = logging.getLogger()

ID = ''
if len(sys.argv) > 1:
  ID = sys.argv[1]
else:
  print('Usage: reddit-dl.py <post_id>')
  exit(1)

# authreq = {
#   'grant_type': 'https://oauth.reddit.com/grants/installed_client',
#   'device_id': 'DO_NOT_TRACK_THIS_DEVICE'
# }
# auth = requests.post(
#   url='https://www.reddit.com/api/v1/access_token',
#   data=authreq,
#   auth=(OAUTH_USER, OAUTH_SECRET),
#   headers={'User-agent': USER_AGENT}
# )
# token = auth.json().get('access_token', '?')
# log.info(f"AUTH {auth.status_code}:{auth.json()}, using token {token}")
#
# if auth.status_code != 200:
#   exit(1)

url = f"https://api.reddit.com/api/info/?id=t3_{ID}"
log.info(f"Requesting {url}")
r = requests.get(
  url,
  headers={
    'User-agent': USER_AGENT
  }
)

content = r.json()
log.info(f"{r.status_code}:{content}")

if not 200 == r.status_code:
  log.error(f"Unexpected status code {r.status_code}")
  exit(1)
if not content['data']['children']:
  log.error(f"Content has no 'children'")
  exit(1)
if not content['data']['children'][0]['data']['media']:
  log.error(f"Content has no 'media'")
  exit(1)
if not content['data']['children'][0]['data']['media']['reddit_video']:
  log.error(f"Content has no 'reddit_video'")
  exit(1)

postinfo = VideoPost(
  title=content['data']['children'][0]['data']['title'],
  postBaseUrl=content['data']['children'][0]['data']['url'],
  videoUrl=content['data']['children'][0]['data']['media']['reddit_video']['fallback_url'],
  hlsUrl=content['data']['children'][0]['data']['media']['reddit_video']['hls_url'],
)
log.info(postinfo)
log.info(f"Using video stream from {postinfo.videoUrl}")

# get audio info

r = requests.get(
  postinfo.hlsUrl,
  headers={
    'User-agent': USER_AGENT
  }
)

hlsContent = r.content.decode('UTF-8')
mediaUris = []
for line in hlsContent.split('\n'):
  line: str
  if re.match('.*HLS_AUDIO.*', line):
    log.debug(f"Found audio media-uri: {line}")
    mediaUris.append(extractMediaUri(line))

if len(mediaUris) > 1:
  mediaUris.sort(key=lambda t: t[1], reverse=True)
  audioUri = mediaUris[0]
  postinfo.setAudioUrl(f"{postinfo.postBaseUrl}/{audioUri[0].replace('.m3u8', '.aac')}")
  log.info(f"Using {audioUri[1]}_K audio stream from {postinfo.audioUrl}")
else:
  log.info("No audio URI found")

# download and merge

videoFile = f"{ID}_video.mp4"
audioFile = f"{ID}_audio.aac"

outputFile = f"{ID}.mp4"
finalFile = f"{postinfo.title[:240]}.mp4"  # ffmpeg seems to have issues with filenames

writeContentToFile(postinfo.videoUrl, videoFile)

if postinfo.audioUrl:
  writeContentToFile(postinfo.audioUrl, audioFile)
  log.info("Merging streams using ffmpeg")

  if os.path.exists(outputFile):
    log.info('Removing existing output file')
    os.remove(outputFile)
  if os.path.exists(finalFile):
    log.info('Removing existing final file')
    os.remove(finalFile)

  # ffmpeg -i input.mp4 -i input.aac -c copy -map 0:v:0 -map 1:a:0 output.mp4
  cmd = [FFMPEG, '-i', videoFile, '-i', audioFile,
         '-c', 'copy', '-map', '0:v:0', '-map', '1:a:0',
         outputFile]
  log.info(f"{' '.join(cmd)}")
  p = subprocess.check_output(cmd, stderr=subprocess.STDOUT, shell=False)
  log.debug(p.decode('UTF-8'))

  os.rename(outputFile, finalFile)
  os.remove(audioFile)
else:
  os.rename(videoFile, finalFile)

os.remove(videoFile)
log.info(f"Wrote {int(os.stat(finalFile).st_size / 1024)} KB to '{finalFile}'")
