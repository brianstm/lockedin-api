from flask import Flask, request, jsonify
import requests

app = Flask(__name__)

WOLFRAM_CAREER_API_URL = "https://www.wolframcloud.com/obj/e1295317/CareerRecommendationAPI"
WOLFRAM_ROADMAP_API_URL = "https://www.wolframcloud.com/obj/e1295317/LearningRoadmapAPI"

@app.route('/career-recommendation', methods=['POST'])
def career_recommendation():
    data = request.json
    user_profile = data.get('userProfile', {})
    
    skills = user_profile.get('skills', [])
    interests = user_profile.get('interests', [])
    experience = user_profile.get('experience', 0)
    education = user_profile.get('education', '')
    desired_salary = user_profile.get('desiredSalary', 0)
    
    response = requests.post(WOLFRAM_CAREER_API_URL, json={
        "skills": skills,
        "interests": interests,
        "experience": experience,
        "education": education,
        "desiredSalary": desired_salary
    })
    
    print("Status Code:", response.status_code)
    print("Response Text:", response.text)

    if response.status_code != 200:
        return jsonify({"error": "Error from Wolfram API", "status_code": response.status_code}), response.status_code
    
    try:
        recommendation = response.json()
    except requests.exceptions.JSONDecodeError:
        return jsonify({"error": "Invalid JSON received from Wolfram API", "response": response.text}), 500

    return jsonify({
        "recommendation": recommendation,
        "userProfile": user_profile
    })

@app.route('/learning-roadmap', methods=['POST'])
def learning_roadmap():
    data = request.json
    career = data.get('career', '')
    
    response = requests.post(WOLFRAM_ROADMAP_API_URL, json={
        "career": career
    })
    
    roadmap = response.json()
    
    return jsonify({
        "roadmap": roadmap,
        "career": career
    })

if __name__ == '__main__':
    app.run(debug=True, port=8000)
