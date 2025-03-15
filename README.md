# LockedIn API

A Flask-based API for the LockedIn productivity tracking application.

## Environment Variables

Before deploying, make sure to set up the following environment variables in your Vercel project:

```
FIREBASE_TYPE=
FIREBASE_PROJECT_ID=
FIREBASE_PRIVATE_KEY_ID=
FIREBASE_PRIVATE_KEY=
FIREBASE_CLIENT_EMAIL=
FIREBASE_CLIENT_ID=
FIREBASE_AUTH_URI=
FIREBASE_TOKEN_URI=
FIREBASE_AUTH_PROVIDER_X509_CERT_URL=
FIREBASE_CLIENT_X509_CERT_URL=
FIREBASE_UNIVERSE_DOMAIN=
GOOGLE_GEMINI_KEY=
```

## Deployment Steps

1. Push your code to GitHub:
```bash
git init
git add .
git commit -m "Initial commit"
git branch -M main
git remote add origin <your-github-repo-url>
git push -u origin main
```

2. Import your GitHub repository in Vercel:
   - Go to [Vercel Dashboard](https://vercel.com/dashboard)
   - Click "Add New Project"
   - Import your GitHub repository
   - Configure the environment variables
   - Deploy!

## API Endpoints

### Authentication
- POST `/login` - User login
- POST `/register` - User registration

### Sessions
- POST `/session/start` - Start a new session
- POST `/session/end` - End a session
- GET `/session/<sessionId>/details` - Get session details
- GET `/sessions/recent` - Get recent sessions

### Quiz
- POST `/quiz/generate` - Generate a new quiz
- GET `/quiz/<quizId>` - Get quiz details
- POST `/quiz/submit` - Submit quiz answers
- GET `/quiz/history` - Get quiz history

### Dashboard
- GET `/dashboard/<userId>` - Get user dashboard data

### Stats
- GET `/stats/productivity` - Get productivity statistics
- GET `/stats/applications` - Get application usage statistics

### Groups
- GET `/groups` - Get all groups
- POST `/groups/create` - Create a new group
- POST `/groups/join` - Join a group
- GET `/groups/<groupName>/members` - Get group members

### App Classification
- POST `/classify-apps` - Classify applications
- POST `/classify-apps/local` - Local app classification
- POST `/classify-apps/cached` - Cached app classification
- POST `/classify-apps/update` - Update app classification
- GET `/classify-apps/all` - Get all app classifications
