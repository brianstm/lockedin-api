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

db = firestore.client()

GOOGLE_GEMINI_KEY = os.getenv("GOOGLE_GEMINI_KEY")
genai.configure(api_key=GOOGLE_GEMINI_KEY)

app = Flask(__name__)

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
    


import app_tracker
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

        threading.Thread(target=stop_tracking, args=(duration,session_ref.id)).start()

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

        prompt = "Evaluate how many productivity score for my Computer Science study of this activities, ONLY OUTPUT A FLOAT FROM 0 to 10.0 " + session_data.get("activities")      
        
        model = genai.GenerativeModel("gemini-2.0-flash")
        response = model.generate_content(prompt)

        productivityScore = response.text

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
def getActivity(sessionId):
    try:
        group_ref = db.collection('groups').document(groupId)
        group_data = group_ref.get().to_dict()

        members = group_data.get('members')

        sorted_members = sorted(members, key=lambda x: x.get('score', 0), reverse=True)

        return jsonify({
            "leaderboard": sorted_members,
        }), 200
    
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    



"GROUP MANAGEMENT"
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
            'members': [userID],  
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
        
        members.append(userID) 
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
        group_query = db.collection('groups').where('groupName', '==', groupName).stream()

        group_data = None
        for group_doc in group_query:
            group_data = group_doc.to_dict()
            break  # Get the first matching group

        if not group_data:
            return jsonify({"error": "Group not found"}), 404

        return jsonify(group_data), 200

    
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, debug=True)


    


