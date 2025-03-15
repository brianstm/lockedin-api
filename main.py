import app_tracker
import os
import json
import time
import threading
from datetime import timedelta
import firebase_admin
from firebase_admin import credentials, auth, firestore
from dotenv import load_dotenv
from flask import Flask, request, jsonify
import google.generativeai as genai
import uuid
import random
from flask_cors import CORS


# Load environment variables
load_dotenv()

# Firebase credentials setup
firebase_credentials = {
    "type": os.getenv("FIREBASE_TYPE"),
    "project_id": os.getenv("FIREBASE_PROJECT_ID"),
    "private_key_id": os.getenv("FIREBASE_PRIVATE_KEY_ID"),
    "private_key": os.getenv("FIREBASE_PRIVATE_KEY").replace("\\n", "\n"),
    "client_email": os.getenv("FIREBASE_CLIENT_EMAIL"),
    "client_id": os.getenv("FIREBASE_CLIENT_ID"),
    "auth_uri": os.getenv("FIREBASE_AUTH_URI"),
    "token_uri": os.getenv("FIREBASE_TOKEN_URI"),
    "auth_provider_x509_cert_url": os.getenv("FIREBASE_AUTH_PROVIDER_X509_CERT_URL"),
    "client_x509_cert_url": os.getenv("FIREBASE_CLIENT_X509_CERT_URL"),
    "universe_domain": os.getenv("FIREBASE_UNIVERSE_DOMAIN"),
}

cred = credentials.Certificate(firebase_credentials)
firebase_admin.initialize_app(cred)
db = firestore.client()

GOOGLE_GEMINI_KEY = os.getenv("GOOGLE_GEMINI_KEY")
genai.configure(api_key=GOOGLE_GEMINI_KEY)

app = Flask(__name__)
CORS(app)

# Global cache for app classifications
app_classification_cache = {}

# Load app classifications from Firestore on startup
def load_app_classifications():
    try:
        classifications_ref = db.collection('app_classifications').document('cache')
        doc = classifications_ref.get()
        
        if doc.exists:
            global app_classification_cache
            app_classification_cache = doc.to_dict() or {}
            print(f"Loaded {len(app_classification_cache)} app classifications from Firestore")
    except Exception as e:
        print(f"Error loading app classifications: {e}")

# Save app classifications to Firestore
def save_app_classifications():
    try:
        classifications_ref = db.collection('app_classifications').document('cache')
        classifications_ref.set(app_classification_cache)
        print(f"Saved {len(app_classification_cache)} app classifications to Firestore")
    except Exception as e:
        print(f"Error saving app classifications: {e}")

# Load classifications on startup
load_app_classifications()

@app.route("/", methods=["GET"])
def home():
    return jsonify({"message": "Welcome to LockedIn API"})


@app.route("/generate", methods=["POST"])
def generate_text():
    try:
        data = request.json
        prompt = data.get("prompt")

        if not prompt:
            return jsonify({"error": "Missing prompt"}), 400

        model = genai.GenerativeModel("gemini-2.0-flash")
        response = model.generate_content(prompt)

        return jsonify({"response": response.text})

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/login', methods=['POST'])
def login():
    data = request.json
    email = data.get('email')
    password = data.get('password')

    if not email or not password:
        return jsonify({"error": "Missing email or password"}), 400

    try:
        user = auth.get_user_by_email(email)
        custom_token = auth.create_custom_token(user.uid).decode("utf-8")

        return jsonify({
            "token": custom_token,
            "userId": user.uid
        }), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/register', methods=['POST'])
def register():
    data = request.json
    username = data.get('username')
    email = data.get('email')
    password = data.get('password')

    if not email or not password:
        return jsonify({"error": "Missing email or password"}), 400

    try:
        user = auth.create_user(
            display_name=username,
            email=email,
            password=password,
        )

        return jsonify({
            "message": "User registered successfully",
            "userId": user.uid
        }), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500


tracker = app_tracker.ApplicationTracker()


def log_activity(sessionId):
    session_ref = db.collection('sessions').document(sessionId)

    report = tracker.get_daily_report()
    activities = ""
    for app, duration in report.items():
        activities += f"{app}: {timedelta(seconds=duration)} \n"

    session_ref.update({
        'activities': activities,
    })


def stop_tracking(duration, sessionId):
    time.sleep(duration * 60)
    tracker.stop_tracking()
    log_activity(sessionId)


@app.route('/session/start', methods=['POST'])
def startSession():
    data = request.json
    groupId = data.get('groupId')
    userId = data.get('userId')
    pomodoro = data.get('pomodoro')
    duration = int(data.get('duration'))

    try:
        session_data = {
            'groupId': groupId,
            'userId': userId,
            'pomodoro': pomodoro,
            'activities': "",
        }

        session_ref = db.collection('sessions').document()
        session_ref.set(session_data)

        tracker.start_tracking()

        threading.Thread(target=stop_tracking, args=(
            duration, session_ref.id)).start()

        return jsonify({
            "message": "Session started",
            "sessionId": session_ref.id,
        }), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/session/end', methods=['POST'])
def endSession():
    data = request.json
    sessionId = data.get('sessionId')

    try:
        log_activity(sessionId)

        tracker.stop_tracking()

        session_ref = db.collection('sessions').document(sessionId)
        session_data = session_ref.get().to_dict()

        prompt = """
            OUTPUT ONLY A FLOAT FROM 0.0 TO 10.0.
            Evaluate the productivity score for a Computer Science student based on the following activity log. Use a grading scheme considering duration of activity where:
            Academic-related activities (including YouTube tutorials) are considered positive.
            Gaming, social media, and non-academic activities are considered negative.
            All other activities are considered neutral.
            Provide a productivity score as a float between 0.0 and 10.0, where 10.0 indicates maximum productivity. 
            OUTPUT ONLY A FLOAT FROM 0.0 TO 10.0.
            Activity Log: """ + session_data.get("activities")

        model = genai.GenerativeModel("gemini-2.0-flash")
        response = model.generate_content(prompt)

        productivityScore = float(response.text)

        userId = session_data.get("userId")
        groupId = session_data.get("groupId")

        group_ref = db.collection('groups').document(groupId)
        group_data = group_ref.get().to_dict()

        members = group_data.get('members')

        for member in members:
            if member.get('userId') == userId:
                member['score'] = productivityScore
                break

        group_ref.update({'members': members})

        return jsonify({
            "message": "Session ended",
            "productivityScore": productivityScore,
        }), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/activity/update', methods=['POST'])
def updateActivity():
    data = request.json
    sessionId = data.get('sessionId')

    try:
        log_activity(sessionId)

        return jsonify({'message': 'Activity logged'}), 200

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/activity/<sessionId>', methods=['GET'])
def getActivity(sessionId):
    try:
        log_activity(sessionId)

        session_ref = db.collection('sessions').document(sessionId)
        session_data = session_ref.get().to_dict()

        return jsonify({
            "userId": session_data.get("userId"),
            "userActivities": session_data.get("activities"),
        }), 200

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/leaderboard/<groupId>', methods=['GET'])
def getLeaderboard(groupId):
    try:
        group_ref = db.collection('groups').document(groupId)
        group_data = group_ref.get().to_dict()

        members = group_data.get('members')

        sorted_members = sorted(
            members, key=lambda x: x.get('score', 0), reverse=True)

        return jsonify({
            "leaderboard": sorted_members,
        }), 200

    except Exception as e:
        return jsonify({'error': str(e)}), 500


# "GROUP MANAGEMENT"

@app.route('/groups', methods=['GET'])
def get_all_groups():
    try:
        groups = []
        groups_query = db.collection('groups').stream()

        for group_doc in groups_query:
            group_data = group_doc.to_dict()
            group_data['groupCode'] = group_doc.id
            groups.append(group_data)

        return jsonify({
            "groups": groups
        }), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/groups/create', methods=['POST'])
def create():
    data = request.json
    groupName = data.get('groupName')
    userID = data.get('userId')

    if not groupName:
        return jsonify({"error": "Missing groupName"}), 400

    if not userID:
        return jsonify({"error": "Missing userID"}), 400

    try:
        user = auth.get_user(userID)
        group_ref = db.collection('groups').document()
        group_ref.set({
            'groupName': groupName,
            'createdBy': userID,
            'members': [{"userId": userID, "score": 0}],
            'createdAt': firestore.SERVER_TIMESTAMP
        })

        return jsonify({
            "message": "Group created",
            "groupCode": group_ref.id
        }), 201

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/groups/join', methods=['POST'])
def join():
    data = request.json
    groupCode = data.get('groupCode')
    userID = data.get('userId')

    if not groupCode:
        return jsonify({"error": "Missing groupCode"}), 400

    if not userID:
        return jsonify({"error": "Missing userID"}), 400

    try:
        user = auth.get_user(userID)
        group_ref = db.collection('groups').document(groupCode)
        group_doc = group_ref.get()

        if not group_doc.exists:
            return jsonify({"error": "Group not found"}), 404

        group_data = group_doc.to_dict()
        members = group_data.get('members')

        if userID in members:
            return jsonify({"error": "User already in group"}), 400

        members.append({'userId': userID, 'score': 0})
        group_ref.update({
            'members': members
        })

        return jsonify({
            "message": "User joined group",
            "groupCode": groupCode,
            "members": members
        }), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/groups/<groupName>/members', methods=['GET'])
def get_group(groupName):
    try:
        # Query Firestore for groups with the given groupName
        group_query = db.collection('groups').where(
            'groupName', '==', groupName).stream()

        group_data = None
        for group_doc in group_query:
            group_data = group_doc.to_dict()
            break  # Get the first matching group

        if not group_data:
            return jsonify({"error": "Group not found"}), 404

        return jsonify(group_data), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500


def gemini_generate(prompt, topic=""):
    model = genai.GenerativeModel("gemini-2.0-flash")
    full_prompt = f"{prompt} {topic}"
    response = model.generate_content(full_prompt)
    return jsonify({
        "response": response.text
    })


@app.route('/quiz/generate', methods=['POST'])
def generate_quiz():
    data = request.json
    sessionID = data.get('sessionId')
    userID = data.get('userId')
    topic = data.get('topic')

    if not topic:
        return jsonify({"error": "Missing topic"}), 400

    try:
        question_response = gemini_generate(
            "Generate 5 multiple-choice quiz question about this topic. "
            "The question must be concise and directly related to the topic. "
            "Provide exactly four answer choices labeled A, B, C, and D. "
            "Do not include explanations, just directly return the question and options.", topic)
        question_text = question_response.get_json()['response']

        correct_answer_response = gemini_generate(
            "For the following multiple-choice question, return only the correct answer letter. "
            "Respond with only a single character: A, B, C, or D. "
            "Do not include explanations, introductions, or extra text. "
            "Just return the correct answer letter.")
        correct_answer = correct_answer_response.get_json()['response']

        quizId = str(uuid.uuid4())

        quiz = {
            "quizId": quizId,
            "topic": topic,
            "questions": [
                {
                    "questionText": question_text,
                    "options": ['A', 'B', 'C', 'D'],
                    "answers": correct_answer,
                }
            ],
        }

        return jsonify(quiz), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/user/<userId>', methods=['GET'])
def get_user_profile(userId):
    try:
        user = auth.get_user(userId)

        sessions = []
        sessions_query = db.collection('sessions').where(
            'userId', '==', userId).stream()

        for session_doc in sessions_query:
            session_data = session_doc.to_dict()
            session_data['sessionId'] = session_doc.id
            sessions.append(session_data)

        user_groups = []
        groups_query = db.collection('groups').stream()

        for group_doc in groups_query:
            group_data = group_doc.to_dict()
            members = group_data.get('members', [])

            if any(member.get('userId') == userId for member in members):
                group_data['groupId'] = group_doc.id
                user_groups.append(group_data)

        return jsonify({
            "userId": user.uid,
            "displayName": user.display_name,
            "email": user.email,
            "sessions": sessions,
            "groups": user_groups
        }), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/user/<userId>/sessions', methods=['GET'])
def get_user_sessions(userId):
    try:
        limit = request.args.get('limit', default=10, type=int)
        start_after = request.args.get('startAfter', default=None, type=str)

        query = db.collection('sessions').where('userId', '==', userId).order_by(
            'createdAt', direction=firestore.Query.DESCENDING).limit(limit)

        if start_after:
            start_doc = db.collection('sessions').document(start_after).get()
            if start_doc.exists:
                query = query.start_after(start_doc)

        sessions = []
        for doc in query.stream():
            session_data = doc.to_dict()
            session_data['sessionId'] = doc.id
            sessions.append(session_data)

        return jsonify({
            "userId": userId,
            "sessions": sessions,
            "hasMore": len(sessions) == limit
        }), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/session/<sessionId>/details', methods=['GET'])
def get_session_details(sessionId):
    try:
        session_ref = db.collection('sessions').document(sessionId)
        session_data = session_ref.get().to_dict()

        if not session_data:
            return jsonify({"error": "Session not found"}), 404

        activities = session_data.get("activities", "")

        active_windows = []
        for line in activities.split("\n"):
            if ": " in line:
                app_name, duration_str = line.split(": ", 1)
                app_name = app_name.strip()

                if not app_name:
                    continue

                time_parts = duration_str.strip().split(":")
                if len(time_parts) == 3:
                    try:
                        hours = int(time_parts[0])
                        minutes = int(time_parts[1])
                        seconds = int(time_parts[2])
                        total_seconds = hours * 3600 + minutes * 60 + seconds

                        active_windows.append({
                            "name": app_name,
                            "duration": duration_str.strip(),
                            "seconds": total_seconds
                        })
                    except:
                        pass

        active_windows.sort(key=lambda x: x["seconds"], reverse=True)

        if active_windows:
            app_list = [window['name'] for window in active_windows]
            app_list_str = ', '.join(app_list)

            prompt = f"""
            Classify the following applications as either PRODUCTIVE or DISTRACTING for a student or professional:
            {app_list_str}
            
            Return the classification in a JSON format like this:
            {{
                "classifications": [
                    {{"app": "application name", "category": "PRODUCTIVE"}},
                    {{"app": "application name", "category": "DISTRACTING"}},
                    ...
                ]
            }}
            
            Consider coding environments, educational websites, document editors, and productivity tools as PRODUCTIVE.
            Consider games, social media, entertainment, and streaming sites as DISTRACTING.
            Only use the categories PRODUCTIVE or DISTRACTING. Return valid JSON.
            """

            model = genai.GenerativeModel("gemini-2.0-flash")
            response = model.generate_content(prompt)

            try:
                classifications = json.loads(response.text)

                focused_time = 0
                distracted_time = 0

                for window in active_windows:
                    app_name = window['name']
                    seconds = window['seconds']

                    category = "NEUTRAL"
                    for classification in classifications.get('classifications', []):
                        if classification.get('app') == app_name:
                            category = classification.get('category')
                            break

                    window['category'] = category

                    if category == "PRODUCTIVE":
                        focused_time += seconds
                    elif category == "DISTRACTING":
                        distracted_time += seconds

            except Exception as e:
                print(f"Error parsing Gemini response: {e}")
                focused_time = sum([w['seconds'] for w in active_windows if any(prod in w['name'].lower() for prod in
                                                                                ['code', 'doc', 'excel', 'word', 'pdf', 'study', 'learn', 'read', 'write', 'notes'])])
                distracted_time = sum([w['seconds'] for w in active_windows if any(dist in w['name'].lower() for dist in
                                                                                   ['game', 'play', 'netflix', 'youtube', 'facebook', 'twitter', 'instagram', 'tiktok'])])
        else:
            focused_time = 0
            distracted_time = 0

        productivity_score = session_data.get("productivityScore", 0)
        if productivity_score == 0 and activities:
            prompt = f"""
            Evaluate the productivity score for this activity log. 
            Consider coding environments, educational websites, document editors, and productivity tools as PRODUCTIVE.
            Consider games, social media, entertainment, and streaming sites as DISTRACTING.
            Return ONLY a single number between 0 and 10 as the productivity score.
            
            Activity Log:
            {activities}
            """

            try:
                model = genai.GenerativeModel("gemini-2.0-flash")
                response = model.generate_content(prompt)
                productivity_score = float(response.text.strip())
            except:
                if focused_time + distracted_time > 0:
                    productivity_score = min(
                        10, max(0, 10 * (focused_time / (focused_time + distracted_time))))
                else:
                    productivity_score = 0

        total_seconds = focused_time + distracted_time
        hours = total_seconds // 3600
        minutes = (total_seconds % 3600) // 60
        duration = f"{hours}h {minutes}m" if hours > 0 else f"{minutes} minutes"

        created_at = session_data.get("createdAt")
        date_str = "Unknown date"
        if created_at:
            from datetime import datetime
            if isinstance(created_at, datetime):
                date_str = created_at.strftime("%Y-%m-%d")

        response_data = {
            "sessionId": sessionId,
            "userId": session_data.get("userId"),
            "groupId": session_data.get("groupId"),
            "pomodoro": session_data.get("pomodoro", False),
            "activities": activities,
            "date": date_str,
            "duration": duration,
            "productivityScore": round(productivity_score, 1),
            "focusedTime": focused_time,
            "distractedTime": distracted_time,
            "activeWindows": active_windows[:10]
        }

        return jsonify(response_data), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/stats/productivity', methods=['GET'])
def get_productivity_stats():
    try:
        userId = request.args.get('userId')
        period = request.args.get('period', default='week', type=str)

        if not userId:
            return jsonify({"error": "Missing userId parameter"}), 400

        now = time.time()

        if period == 'day':
            start_time = now - (24 * 60 * 60)
        elif period == 'week':
            start_time = now - (7 * 24 * 60 * 60)
        elif period == 'month':
            start_time = now - (30 * 24 * 60 * 60)
        else:
            return jsonify({"error": "Invalid period. Use 'day', 'week', or 'month'"}), 400

        sessions = []
        sessions_query = db.collection('sessions').where(
            'userId', '==', userId).stream()

        total_score = 0
        session_count = 0

        for session_doc in sessions_query:
            session_data = session_doc.to_dict()

            if 'productivityScore' not in session_data:
                continue

            sessions.append({
                "sessionId": session_doc.id,
                "productivityScore": session_data.get("productivityScore", 0),
                "activities": session_data.get("activities", "")
            })

            total_score += session_data.get("productivityScore", 0)
            session_count += 1

        avg_score = total_score / max(session_count, 1)

        return jsonify({
            "userId": userId,
            "period": period,
            "averageProductivityScore": round(avg_score, 2),
            "sessionCount": session_count,
            "sessions": sessions
        }), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/stats/applications', methods=['GET'])
def get_app_usage_stats():
    try:
        userId = request.args.get('userId')

        if not userId:
            return jsonify({"error": "Missing userId parameter"}), 400

        sessions_query = db.collection('sessions').where(
            'userId', '==', userId).stream()

        app_usage = {}

        for session_doc in sessions_query:
            session_data = session_doc.to_dict()
            activities = session_data.get("activities", "")

            for line in activities.split("\n"):
                if ": " in line:
                    app_name, duration_str = line.split(": ", 1)
                    app_name = app_name.strip()

                    if not app_name:
                        continue

                    time_parts = duration_str.strip().split(":")
                    if len(time_parts) == 3:
                        try:
                            hours = int(time_parts[0])
                            minutes = int(time_parts[1])
                            seconds = int(time_parts[2])
                            total_seconds = hours * 3600 + minutes * 60 + seconds

                            if app_name in app_usage:
                                app_usage[app_name] += total_seconds
                            else:
                                app_usage[app_name] = total_seconds
                        except:
                            pass

        formatted_usage = {}
        for app, seconds in app_usage.items():
            hours = seconds // 3600
            minutes = (seconds % 3600) // 60
            remaining_seconds = seconds % 60
            formatted_usage[app] = {
                "totalSeconds": seconds,
                "formatted": f"{hours}:{minutes:02d}:{remaining_seconds:02d}"
            }

        sorted_usage = dict(sorted(formatted_usage.items(),
                            key=lambda x: x[1]["totalSeconds"], reverse=True))

        return jsonify({
            "userId": userId,
            "appUsage": sorted_usage
        }), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/quiz/history', methods=['GET'])
def get_quiz_history():
    try:
        userId = request.args.get('userId')

        if not userId:
            return jsonify({"error": "Missing userId parameter"}), 400

        quizzes = []
        quizzes_query = db.collection('quizzes').where(
            'userId', '==', userId).stream()

        for quiz_doc in quizzes_query:
            quiz_data = quiz_doc.to_dict()
            quiz_data['quizId'] = quiz_doc.id
            quizzes.append(quiz_data)

        return jsonify({
            "userId": userId,
            "quizzes": quizzes
        }), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/sessions/recent', methods=['GET'])
def get_recent_sessions():
    try:
        userId = request.args.get('userId')
        limit = request.args.get('limit', default=5, type=int)

        if not userId:
            return jsonify({"error": "Missing userId parameter"}), 400

        sessions_query = db.collection('sessions')\
            .where('userId', '==', userId)\
            .order_by('createdAt', direction=firestore.Query.DESCENDING)\
            .limit(limit)

        recent_sessions = []
        for doc in sessions_query.stream():
            session_data = doc.to_dict()
            session_data['sessionId'] = doc.id

            if 'createdAt' not in session_data or not session_data['createdAt']:
                session_data['createdAt'] = firestore.SERVER_TIMESTAMP

            activities = session_data.get("activities", "")

            app_names = []
            for line in activities.split("\n"):
                if ": " in line:
                    app_name, _ = line.split(": ", 1)
                    app_name = app_name.strip()
                    if app_name and app_name not in app_names:
                        app_names.append(app_name)

            productivity_score = session_data.get("productivityScore", 0)
            if productivity_score == 0 and activities:
                prompt = f"""
                Evaluate the productivity score for this activity log.
                Consider coding environments, educational websites, document editors, and productivity tools as PRODUCTIVE.
                Consider games, social media, entertainment, and streaming sites as DISTRACTING.
                Return ONLY a single number between 0 and 10 as the productivity score.
                
                Activity Log:
                {activities}
                """

                try:
                    model = genai.GenerativeModel("gemini-2.0-flash")
                    response = model.generate_content(prompt)
                    productivity_score = float(response.text.strip())

                    db.collection('sessions').document(doc.id).update({
                        'productivityScore': productivity_score
                    })
                except Exception as e:
                    print(f"Error calculating productivity score: {e}")
                    productivity_score = 5

            total_seconds = 0
            focused_time = 0
            distracted_time = 0

            for line in activities.split("\n"):
                if ": " in line:
                    app_name, duration_str = line.split(": ", 1)
                    app_name = app_name.strip()

                    if not app_name:
                        continue

                    time_parts = duration_str.strip().split(":")
                    if len(time_parts) == 3:
                        try:
                            hours = int(time_parts[0])
                            minutes = int(time_parts[1])
                            seconds = int(time_parts[2])
                            total_seconds += hours * 3600 + minutes * 60 + seconds
                        except:
                            pass

            hours = total_seconds // 3600
            minutes = (total_seconds % 3600) // 60
            duration = f"{hours}h {minutes}m" if hours > 0 else f"{minutes} minutes"

            created_at = session_data.get("createdAt")
            date_str = "Unknown date"
            if created_at:
                from datetime import datetime
                if isinstance(created_at, datetime):
                    date_str = created_at.strftime("%Y-%m-%d")

            simplified_session = {
                "sessionId": doc.id,
                "date": date_str,
                "duration": duration,
                "productivityScore": round(productivity_score, 1),
                "appCount": len(app_names),
                "topApps": app_names[:3]
            }

            recent_sessions.append(simplified_session)

        return jsonify({
            "userId": userId,
            "recentSessions": recent_sessions
        }), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/session/<sessionId>/activity-data', methods=['GET'])
def get_session_activity_data(sessionId):
    try:
        session_ref = db.collection('sessions').document(sessionId)
        session_data = session_ref.get().to_dict()

        if not session_data:
            return jsonify({"error": "Session not found"}), 404

        activities = session_data.get("activities", "")

        activity_data = []
        app_totals = {}

        for line in activities.split("\n"):
            if ": " in line:
                app_name, duration_str = line.split(": ", 1)
                app_name = app_name.strip()

                if not app_name:
                    continue

                time_parts = duration_str.strip().split(":")
                if len(time_parts) == 3:
                    try:
                        hours = int(time_parts[0])
                        minutes = int(time_parts[1])
                        seconds = int(time_parts[2])
                        total_seconds = hours * 3600 + minutes * 60 + seconds

                        if app_name in app_totals:
                            app_totals[app_name] += total_seconds
                        else:
                            app_totals[app_name] = total_seconds
                    except:
                        pass

        for app, seconds in app_totals.items():
            hours = seconds // 3600
            minutes = (seconds % 3600) // 60
            remaining_seconds = seconds % 60

            activity_data.append({
                "name": app,
                "seconds": seconds,
                "formattedTime": f"{hours}:{minutes:02d}:{remaining_seconds:02d}"
            })

        activity_data.sort(key=lambda x: x["seconds"], reverse=True)

        if activity_data:
            app_list = [item['name'] for item in activity_data]
            app_list_str = ', '.join(app_list)

            prompt = f"""
            Classify the following applications as either PRODUCTIVE or DISTRACTING for a student or professional:
            {app_list_str}
            
            Return the classification in a JSON format like this:
            {{
                "classifications": [
                    {{"app": "application name", "category": "PRODUCTIVE"}},
                    {{"app": "application name", "category": "DISTRACTING"}},
                    ...
                ]
            }}
            
            Consider coding environments, educational websites, document editors, and productivity tools as PRODUCTIVE.
            Consider games, social media, entertainment, and streaming sites as DISTRACTING.
            Only use the categories PRODUCTIVE or DISTRACTING. Return valid JSON.
            """

            model = genai.GenerativeModel("gemini-2.0-flash")
            response = model.generate_content(prompt)

            try:
                classifications = json.loads(response.text)

                for item in activity_data:
                    app_name = item['name']

                    category = "NEUTRAL"
                    for classification in classifications.get('classifications', []):
                        if classification.get('app') == app_name:
                            category = classification.get('category')
                            break

                    item['category'] = category
            except Exception as e:
                print(f"Error parsing Gemini response: {e}")
                for item in activity_data:
                    item['category'] = "NEUTRAL"

        total_time = sum(item['seconds'] for item in activity_data)
        productive_time = sum(item['seconds'] for item in activity_data if item.get(
            'category') == 'PRODUCTIVE')
        distracting_time = sum(item['seconds'] for item in activity_data if item.get(
            'category') == 'DISTRACTING')

        def format_time(seconds):
            hours = seconds // 3600
            minutes = (seconds % 3600) // 60
            return f"{hours}h {minutes}m" if hours > 0 else f"{minutes}m"

        summary = {
            "totalTime": format_time(total_time),
            "totalSeconds": total_time,
            "productiveTime": format_time(productive_time),
            "productiveSeconds": productive_time,
            "distractingTime": format_time(distracting_time),
            "distractingSeconds": distracting_time,
            "productivityRatio": round(productive_time / max(1, total_time) * 100, 1)
        }

        return jsonify({
            "sessionId": sessionId,
            "activityData": activity_data,
            "summary": summary
        }), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/classify-apps', methods=['POST'])
def classify_apps():
    try:
        data = request.json
        app_names = data.get('appNames', [])
        
        if not app_names or not isinstance(app_names, list):
            return jsonify({"error": "Missing or invalid appNames parameter. Expected a list of strings."}), 400
        
        if len(app_names) == 0:
            return jsonify({"classifications": []}), 200
            
        app_list_str = ', '.join(app_names)
        
        prompt = f"""
        Classify the following applications as either PRODUCTIVE or DISTRACTING for a student or professional:
        {app_list_str}
        
        Return the classification in a JSON format like this:
        {{
            "classifications": [
                {{"app": "application name", "category": "PRODUCTIVE"}},
                {{"app": "application name", "category": "DISTRACTING"}},
                ...
            ]
        }}
        
        Consider coding environments, educational websites, document editors, productivity tools, 
        and learning platforms as PRODUCTIVE.
        
        Consider games, social media, entertainment, streaming sites, and non-educational video 
        platforms as DISTRACTING.
        
        Only use the categories PRODUCTIVE or DISTRACTING. Return valid JSON.
        """
        
        model = genai.GenerativeModel("gemini-2.0-flash")
        response = model.generate_content(prompt)
        
        try:
            classifications = json.loads(response.text)
            return jsonify(classifications), 200
        except json.JSONDecodeError:
            # Fallback classification if Gemini doesn't return valid JSON
            fallback_classifications = {"classifications": []}
            
            productive_keywords = [
                "code", "visual studio", "intellij", "pycharm", "webstorm", "eclipse", 
                "xcode", "android studio", "sublime", "atom", "notepad", "textedit",
                "word", "excel", "powerpoint", "docs", "sheets", "slides", 
                "notion", "evernote", "onenote", "google drive", "dropbox", "onedrive",
                "slack", "teams", "zoom", "meet", "webex", "discord",
                "github", "gitlab", "bitbucket", "stackoverflow", "canvas", "blackboard",
                "moodle", "coursera", "udemy", "edx", "khan academy", "duolingo",
                "terminal", "command prompt", "powershell", "bash", "zsh", "cmd",
                "calculator", "calendar", "mail", "outlook", "gmail", "pdf"
            ]
            
            distracting_keywords = [
                "game", "steam", "epic games", "origin", "battle.net", "uplay",
                "facebook", "twitter", "instagram", "tiktok", "snapchat", "reddit",
                "youtube", "twitch", "netflix", "hulu", "disney+", "amazon prime",
                "spotify", "apple music", "tidal", "pandora", "soundcloud",
                "messaging", "whatsapp", "telegram", "signal", "wechat", "line"
            ]
            
            for app in app_names:
                app_lower = app.lower()
                
                is_productive = any(keyword in app_lower for keyword in productive_keywords)
                is_distracting = any(keyword in app_lower for keyword in distracting_keywords)
                
                if is_productive and not is_distracting:
                    category = "PRODUCTIVE"
                elif is_distracting and not is_productive:
                    category = "DISTRACTING"
                else:
                    # If ambiguous or neither, default to NEUTRAL
                    category = "NEUTRAL"
                
                fallback_classifications["classifications"].append({
                    "app": app,
                    "category": category
                })
            
            return jsonify(fallback_classifications), 200
            
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/classify-apps/local', methods=['POST'])
def classify_apps_local():
    try:
        data = request.json
        app_names = data.get('appNames', [])
        
        if not app_names or not isinstance(app_names, list):
            return jsonify({"error": "Missing or invalid appNames parameter. Expected a list of strings."}), 400
        
        if len(app_names) == 0:
            return jsonify({"classifications": []}), 200
        
        productive_keywords = [
            "code", "visual studio", "intellij", "pycharm", "webstorm", "eclipse", 
            "xcode", "android studio", "sublime", "atom", "notepad", "textedit",
            "word", "excel", "powerpoint", "docs", "sheets", "slides", 
            "notion", "evernote", "onenote", "google drive", "dropbox", "onedrive",
            "slack", "teams", "zoom", "meet", "webex", "discord",
            "github", "gitlab", "bitbucket", "stackoverflow", "canvas", "blackboard",
            "moodle", "coursera", "udemy", "edx", "khan academy", "duolingo",
            "terminal", "command prompt", "powershell", "bash", "zsh", "cmd",
            "calculator", "calendar", "mail", "outlook", "gmail", "pdf",
            "chrome - canvas", "chrome - github", "chrome - gitlab", "chrome - stackoverflow",
            "chrome - docs", "chrome - sheets", "chrome - slides", "chrome - drive",
            "firefox - canvas", "firefox - github", "firefox - gitlab", "firefox - stackoverflow",
            "firefox - docs", "firefox - sheets", "firefox - slides", "firefox - drive"
        ]
        
        distracting_keywords = [
            "game", "steam", "epic games", "origin", "battle.net", "uplay",
            "facebook", "twitter", "instagram", "tiktok", "snapchat", "reddit",
            "youtube", "twitch", "netflix", "hulu", "disney+", "amazon prime",
            "spotify", "apple music", "tidal", "pandora", "soundcloud",
            "messaging", "whatsapp", "telegram", "signal", "wechat", "line",
            "chrome - facebook", "chrome - twitter", "chrome - instagram", "chrome - tiktok",
            "chrome - reddit", "chrome - youtube", "chrome - twitch", "chrome - netflix",
            "firefox - facebook", "firefox - twitter", "firefox - instagram", "firefox - tiktok",
            "firefox - reddit", "firefox - youtube", "firefox - twitch", "firefox - netflix"
        ]
        
        classifications = {"classifications": []}
        
        for app in app_names:
            app_lower = app.lower()
            
            is_productive = any(keyword in app_lower for keyword in productive_keywords)
            is_distracting = any(keyword in app_lower for keyword in distracting_keywords)
            
            if is_productive and not is_distracting:
                category = "PRODUCTIVE"
            elif is_distracting and not is_productive:
                category = "DISTRACTING"
            else:
                category = "NEUTRAL"
            
            classifications["classifications"].append({
                "app": app,
                "category": category
            })
        
        return jsonify(classifications), 200
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/classify-apps/cached', methods=['POST'])
def classify_apps_cached():
    try:
        data = request.json
        app_names = data.get('appNames', [])
        
        if not app_names or not isinstance(app_names, list):
            return jsonify({"error": "Missing or invalid appNames parameter. Expected a list of strings."}), 400
        
        if len(app_names) == 0:
            return jsonify({"classifications": []}), 200
        
        uncached_apps = [app for app in app_names if app not in app_classification_cache]
        
        if uncached_apps:
            app_list_str = ', '.join(uncached_apps)
            
            prompt = f"""
            Classify the following applications as either PRODUCTIVE or DISTRACTING for a student or professional:
            {app_list_str}
            
            Return the classification in a JSON format like this:
            {{
                "classifications": [
                    {{"app": "application name", "category": "PRODUCTIVE"}},
                    {{"app": "application name", "category": "DISTRACTING"}},
                    ...
                ]
            }}
            
            Consider coding environments, educational websites, document editors, productivity tools, 
            and learning platforms as PRODUCTIVE.
            
            Consider games, social media, entertainment, streaming sites, and non-educational video 
            platforms as DISTRACTING.
            
            Only use the categories PRODUCTIVE or DISTRACTING. Return valid JSON.
            """
            
            try:
                model = genai.GenerativeModel("gemini-2.0-flash")
                response = model.generate_content(prompt)
                
                classifications = json.loads(response.text)
                
                cache_updated = False
                for classification in classifications.get('classifications', []):
                    app = classification.get('app')
                    category = classification.get('category')
                    if app and category:
                        app_classification_cache[app] = category
                        cache_updated = True
                
                if cache_updated:
                    save_app_classifications()
                        
            except (json.JSONDecodeError, Exception) as e:
                productive_keywords = [
                    "code", "visual studio", "intellij", "pycharm", "webstorm", "eclipse", 
                    "xcode", "android studio", "sublime", "atom", "notepad", "textedit",
                    "word", "excel", "powerpoint", "docs", "sheets", "slides", 
                    "notion", "evernote", "onenote", "google drive", "dropbox", "onedrive",
                    "slack", "teams", "zoom", "meet", "webex", "discord",
                    "github", "gitlab", "bitbucket", "stackoverflow", "canvas", "blackboard",
                    "moodle", "coursera", "udemy", "edx", "khan academy", "duolingo",
                    "terminal", "command prompt", "powershell", "bash", "zsh", "cmd",
                    "calculator", "calendar", "mail", "outlook", "gmail", "pdf"
                ]
                
                distracting_keywords = [
                    "game", "steam", "epic games", "origin", "battle.net", "uplay",
                    "facebook", "twitter", "instagram", "tiktok", "snapchat", "reddit",
                    "youtube", "twitch", "netflix", "hulu", "disney+", "amazon prime",
                    "spotify", "apple music", "tidal", "pandora", "soundcloud",
                    "messaging", "whatsapp", "telegram", "signal", "wechat", "line"
                ]
                
                cache_updated = False
                for app in uncached_apps:
                    app_lower = app.lower()
                    
                    is_productive = any(keyword in app_lower for keyword in productive_keywords)
                    is_distracting = any(keyword in app_lower for keyword in distracting_keywords)
                    
                    if is_productive and not is_distracting:
                        category = "PRODUCTIVE"
                    elif is_distracting and not is_productive:
                        category = "DISTRACTING"
                    else:
                        category = "NEUTRAL"
                    
                    app_classification_cache[app] = category
                    cache_updated = True
                
                if cache_updated:
                    save_app_classifications()
        
        result = {"classifications": []}
        for app in app_names:
            category = app_classification_cache.get(app, "NEUTRAL")
            result["classifications"].append({
                "app": app,
                "category": category
            })
        
        return jsonify(result), 200
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/classify-apps/update', methods=['POST'])
def update_app_classification():
    try:
        data = request.json
        app_name = data.get('appName')
        category = data.get('category')
        
        if not app_name:
            return jsonify({"error": "Missing appName parameter"}), 400
            
        if not category or category not in ["PRODUCTIVE", "DISTRACTING", "NEUTRAL"]:
            return jsonify({"error": "Invalid category. Must be one of: PRODUCTIVE, DISTRACTING, NEUTRAL"}), 400
        
        app_classification_cache[app_name] = category
        
        save_app_classifications()
        
        return jsonify({
            "message": f"Successfully updated classification for {app_name} to {category}",
            "app": app_name,
            "category": category
        }), 200
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/classify-apps/all', methods=['GET'])
def get_all_app_classifications():
    try:
        classifications = []
        for app, category in app_classification_cache.items():
            classifications.append({
                "app": app,
                "category": category
            })
        
        classifications.sort(key=lambda x: x["app"])
        
        return jsonify({
            "classifications": classifications,
            "count": len(classifications)
        }), 200
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/dashboard/<userId>', methods=['GET'])
def get_dashboard_data(userId):
    try:
        try:
            user = auth.get_user(userId)
        except:
            return jsonify({"error": "User not found"}), 404

        recent_sessions_query = db.collection('sessions')\
            .where('userId', '==', userId)\
            .order_by('createdAt', direction=firestore.Query.DESCENDING)\
            .limit(5)

        recent_sessions = []
        for doc in recent_sessions_query.stream():
            session_data = doc.to_dict()
            session_data['sessionId'] = doc.id

            created_at = session_data.get("createdAt")
            date_str = "Unknown date"
            if created_at:
                from datetime import datetime
                if isinstance(created_at, datetime):
                    date_str = created_at.strftime("%Y-%m-%d")

            productivity_score = session_data.get("productivityScore", 0)

            activities = session_data.get("activities", "")
            total_seconds = 0
            for line in activities.split("\n"):
                if ": " in line:
                    _, duration_str = line.split(": ", 1)
                    time_parts = duration_str.strip().split(":")
                    if len(time_parts) == 3:
                        try:
                            hours = int(time_parts[0])
                            minutes = int(time_parts[1])
                            seconds = int(time_parts[2])
                            total_seconds += hours * 3600 + minutes * 60 + seconds
                        except:
                            pass

            hours = total_seconds // 3600
            minutes = (total_seconds % 3600) // 60
            duration = f"{hours}h {minutes}m" if hours > 0 else f"{minutes}m"

            session_summary = {
                "sessionId": doc.id,
                "date": date_str,
                "duration": duration,
                "productivityScore": round(productivity_score, 1)
            }

            recent_sessions.append(session_summary)

        all_sessions_query = db.collection('sessions').where(
            'userId', '==', userId).stream()

        total_sessions = 0
        total_time_seconds = 0
        total_productive_seconds = 0
        total_distracting_seconds = 0
        productivity_scores = []

        for doc in all_sessions_query:
            session_data = doc.to_dict()
            total_sessions += 1

            productivity_score = session_data.get("productivityScore", 0)
            if productivity_score > 0:
                productivity_scores.append(productivity_score)

            activities = session_data.get("activities", "")

            app_names = []
            app_durations = {}

            for line in activities.split("\n"):
                if ": " in line:
                    app_name, duration_str = line.split(": ", 1)
                    app_name = app_name.strip()

                    if not app_name:
                        continue

                    if app_name not in app_names:
                        app_names.append(app_name)

                    time_parts = duration_str.strip().split(":")
                    if len(time_parts) == 3:
                        try:
                            hours = int(time_parts[0])
                            minutes = int(time_parts[1])
                            seconds = int(time_parts[2])
                            app_seconds = hours * 3600 + minutes * 60 + seconds

                            total_time_seconds += app_seconds

                            app_durations[app_name] = app_seconds
                        except:
                            pass

            if app_names:
                app_list_str = ', '.join(app_names)

                prompt = f"""
                Classify the following applications as either PRODUCTIVE or DISTRACTING for a student or professional:
                {app_list_str}
                
                Return the classification in a JSON format like this:
                {{
                    "classifications": [
                        {{"app": "application name", "category": "PRODUCTIVE"}},
                        {{"app": "application name", "category": "DISTRACTING"}},
                        ...
                    ]
                }}
                
                Consider coding environments, educational websites, document editors, and productivity tools as PRODUCTIVE.
                Consider games, social media, entertainment, and streaming sites as DISTRACTING.
                Only use the categories PRODUCTIVE or DISTRACTING. Return valid JSON.
                """

                model = genai.GenerativeModel("gemini-2.0-flash")
                response = model.generate_content(prompt)

                try:
                    classifications = json.loads(response.text)

                    for app_name, seconds in app_durations.items():
                        category = "NEUTRAL"
                        for classification in classifications.get('classifications', []):
                            if classification.get('app') == app_name:
                                category = classification.get('category')
                                break

                        if category == "PRODUCTIVE":
                            total_productive_seconds += seconds
                        elif category == "DISTRACTING":
                            total_distracting_seconds += seconds

                except Exception as e:
                    print(f"Error parsing Gemini response: {e}")

        avg_productivity = sum(productivity_scores) / \
            max(1, len(productivity_scores))

        def format_time(seconds):
            hours = seconds // 3600
            minutes = (seconds % 3600) // 60
            return f"{hours}h {minutes}m" if hours > 0 else f"{minutes}m"

        dashboard_data = {
            "userId": userId,
            "displayName": user.display_name,
            "totalSessions": total_sessions,
            "totalTime": format_time(total_time_seconds),
            "totalTimeSeconds": total_time_seconds,
            "productiveTime": format_time(total_productive_seconds),
            "productiveTimeSeconds": total_productive_seconds,
            "distractingTime": format_time(total_distracting_seconds),
            "distractingTimeSeconds": total_distracting_seconds,
            "averageProductivityScore": round(avg_productivity, 1),
            "recentSessions": recent_sessions
        }

        return jsonify(dashboard_data), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, debug=True)
