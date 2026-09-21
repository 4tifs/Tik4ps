# TikTok 60 FPS & High-Quality Web App

A high-performance hybrid web application that optimizes video files for TikTok's 60 FPS and lossless quality ingestion pipeline without re-encoding video frames.

## Architecture

- **Client-Side (In-Browser)**: Remuxes the video locally using WebAssembly FFmpeg (`@ffmpeg/ffmpeg`). The heavy video data (`mdat`) never leaves the user's computer.
- **Serverless API (`api/patch.py`)**: Computes the proprietary atom modifications (`calc_stts_remainder`, `stts`, `mdhd`, `btrt`, `esds`, and Track 3 synthetic chunks) on the ~25 KB `moov` header.
- **Privacy & Speed**: 0 MB cloud storage required, near-zero server bandwidth, sub-second execution.

## Deployment to Vercel (100% Free)

### Step 1: Create a PRIVATE Repository on GitHub
1. Go to [github.com/new](https://github.com/new).
2. Set the repository name (e.g., `tiktok-60fps-app`).
3. **IMPORTANT**: Select **Private** so your serverless formulas in `api/patch.py` remain confidential.
4. Click **Create repository**.

### Step 2: Push This Directory to GitHub
Open your terminal inside this folder (`tiktok-60fps-web`):

```bash
git init
git add .
git commit -m "Initial commit of 60 FPS TikTok web app"
git branch -M main
git remote add origin https://github.com/<your-username>/<your-repo-name>.git
git push -u origin main
```

### Step 3: Connect to Vercel
1. Go to [vercel.com](https://vercel.com) and log in.
2. Click **Add New...** -> **Project**.
3. Import your private repository from GitHub.
4. Leave all build settings at their defaults (Vercel automatically detects the static frontend and Python serverless function).
5. Click **Deploy**.

Your web app will be live globally in seconds!
