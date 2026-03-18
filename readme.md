This repo downloads YouTube transcripts.

## Network requirements

Running the transcript fetching scripts requires direct access to YouTube.
If you are behind a restrictive HTTPS proxy (for example one that blocks
CONNECT requests to `*.youtube.com`) both `yt-dlp` and
`youtube-transcript-api` will fail with `Tunnel connection failed: 403 Forbidden`
errors. In that situation you will need to run the scripts on an unrestricted
network or provide a working proxy before attempting to download transcripts.
