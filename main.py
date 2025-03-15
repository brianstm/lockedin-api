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

        prompt = """
        Analyze this activity log and provide:
        1. Most used productive application
        2. Most used distracting application
        3. Productivity percentage (time spent on productive apps vs total time)
        Return the results in JSON format with the following structure:
        {
            "mostProductiveApp": "app name",
            "mostDistractingApp": "app name",
            "productivityPercentage": 75.5
        }
        Activity Log: """ + activities

        model = genai.GenerativeModel("gemini-2.0-flash")
        response = model.generate_content(prompt)

        try:
            analytics = json.loads(response.text)
        except:
            analytics = {
                "mostProductiveApp": "Unknown",
                "mostDistractingApp": "Unknown",
                "productivityPercentage": 0
            }

        return jsonify({
            "sessionId": sessionId,
            "userId": session_data.get("userId"),
            "groupId": session_data.get("groupId"),
            "pomodoro": session_data.get("pomodoro"),
            "activities": activities,
            "analytics": analytics
        }), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/group/<groupId>/details', methods=['GET'])
def get_group_details(groupId):
    try:
        group_ref = db.collection('groups').document(groupId)
        group_data = group_ref.get().to_dict()

        if not group_data:
            return jsonify({"error": "Group not found"}), 404

        members = group_data.get('members', [])
        detailed_members = []

        for member in members:
            userId = member.get('userId')
            try:
                user = auth.get_user(userId)
                detailed_members.append({
                    "userId": userId,
                    "displayName": user.display_name,
                    "email": user.email,
                    "score": member.get('score', 0)
                })
            except:
                detailed_members.append({
                    "userId": userId,
                    "displayName": "Unknown",
                    "email": "Unknown",
                    "score": member.get('score', 0)
                })

        return jsonify({
            "groupId": groupId,
            "groupName": group_data.get('groupName'),
            "createdBy": group_data.get('createdBy'),
            "createdAt": group_data.get('createdAt'),
            "members": detailed_members
        }), 200

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


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, debug=True)
