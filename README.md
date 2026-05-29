# Project Chanakya - AI Surveillance Command Dashboard

Project Chanakya is a full-stack AI surveillance prototype that connects a React dashboard with a Flask backend. The system monitors live camera feeds, displays AI-generated threat logs, tracks zones, and provides a secure report download option.

## Objective

The objective of this project is to build an AI-powered surveillance system that can monitor live camera feeds, detect objects using YOLOv8, record threat logs, and display security information through a connected web dashboard.

## Features

- Real-time object detection using YOLOv8
- Live camera feed monitoring through Flask video streams
- Threat log dashboard connected to backend API
- Zone-based threat tracking
- Known-person image database for face recognition
- Emotion signal detection using facial landmark analysis
- Telegram alert support for high-risk detections
- Secure incident report download
- Smart surveillance command dashboard built in React
- SQLite-based incident history storage
- AI-assisted monitoring system

## Tech Stack

- React.js
- Vite
- JavaScript
- CSS
- Python
- Flask
- OpenCV
- YOLOv8 / Ultralytics
- Face Recognition
- Facial Landmark Analysis
- SQLite
- Telegram Bot API

## Project Structure

```text
surveillance-ai/
├── Backend/
│   ├── web/app.py
│   ├── src/
│   ├── config/
│   ├── database/
│   ├── models/
│   └── requirement.txt
└── frontend/
    ├── src/
    ├── package.json
    └── vite.config.js
```

## How To Run The Project

Start from the `satellite_ai` folder:

```bash
cd surveillance-ai
```

### 1. Run Backend

Open the first terminal:

```bash
cd Backend
source venv/bin/activate
python web/app.py
```

Backend will run at:

```text
http://127.0.0.1:5001/
```

### 2. Run Frontend

Open a second terminal:

```bash
cd ~/Desktop/satellite_ai/surveillance-ai/frontend
npm run dev -- --host 127.0.0.1
```

Frontend will run at:

```text
http://127.0.0.1:5173/
```

## Backend API Used By Frontend

```text
GET /api/logs
GET /api/modules
GET /video_feed_1
GET /video_feed_2
GET /download_secure_report
```

## Known Face Database

Add authorized person photos inside:

```text
Backend/database/known_faces/
```

You can use either direct image files:

```text
Backend/database/known_faces/Aryan_Negi.jpg
Backend/database/known_faces/Student_01.jpg
```

Or person-wise folders for multiple images:

```text
Backend/database/known_faces/
├── Aryan_Negi/
│   ├── front.jpg
│   └── side.jpg
└── Student_01/
    ├── photo1.jpg
    └── photo2.jpg
```

The backend automatically rebuilds face encodings when known-face images are added or changed.

## Important Notes

- Keep both backend and frontend terminals running at the same time.
- If the live camera does not appear, allow camera permission for the terminal/Codex app and restart the backend.
- If frontend dependencies are missing, run `npm install` inside the `frontend` folder.
- If backend dependencies are missing, activate the virtual environment and run `pip install -r requirement.txt` inside the `Backend` folder.

## Overall Outcome

The final outcome is a working full-stack AI surveillance prototype where the backend performs monitoring and detection tasks, while the frontend displays live feeds, threat metrics, logs, and report download options.

## Future Improvements

- Deep-learning emotion model for higher accuracy
- Satellite map overlay for border, disaster, and remote asset monitoring
- Cloud deployment
- Mobile notifications
- User login and admin authentication
- Better camera permission handling
- Live deployment with hosted frontend and backend
