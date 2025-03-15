def gemini_generate(prompt, topic = "" ):
    model = genai.GenerativeModel("gemini-2.0-flash")
    full_prompt = f"{prompt} {topic}"
    response = model.generate_content(full_prompt)
    return response.text

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
            "Generate a multiple-choice quiz question about this topic. "
            "The question must be concise and directly related to the topic. "
            "Provide exactly four answer choices labeled A, B, C, and D. "
            "Do not include explanations, just directly return the question and options, please directly start with the questions dont talk about anything else.",topic)
        question_text = question_response

        correct_answer_response =  gemini_generate(
            "For the following multiple-choice question, return only the correct answer letter. "
            "Respond with a single character: A, B, C, or D."
            "Do not include explanations, introductions, or extra text."
            "Just return the correct answer letter.")
        correct_answer = correct_answer_response

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
        db.collection('quizzes').document(quizId).set(quiz)

        return jsonify(quiz), 200
    
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    
@app.route('/quiz/<quizId>', methods=['GET'])
def get_quiz(quizId):
    try:
        quiz_ref = db.collection('quizzes').document(quizId)
        quiz_snapshot = quiz_ref.get()

        if not quiz_snapshot.exists:
            return jsonify({"error": "Quiz not found"}), 404

        quiz_data = quiz_snapshot.to_dict()
        return jsonify(quiz_data), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/quiz/submit', methods=['POST'])
def submit_quiz():
    data = request.json
    quizId = data.get('quizId')
    userID = data.get('userId')
    answers = data.get('answers')

    if not quizId:
        return jsonify({"error": "Missing quizId"}), 400
    if not userID:
        return jsonify({"error": "Missing userId"}), 400
    if not answers or not isinstance(answers, list):
        return jsonify({"error": "Answers must be a non-empty list"}), 400

    try:
        quiz_ref = db.collection('quizzes').document(quizId)
        quiz_snapshot = quiz_ref.get()

        if not quiz_snapshot.exists:
            return jsonify({"error": "Quiz not found"}), 404

        quiz_data = quiz_snapshot.to_dict()
        correct_answers = [q.get("answers") for q in quiz_data.get("questions")]

        if not correct_answers:
            return jsonify({"error": "Quiz has no correct answers stored"}), 500

        score = sum(1 for i in range(min(len(answers), len(correct_answers))) if answers[i].get("selectedOption") == correct_answers[i][0:1])
        
        return jsonify({ 
            "score": score,
            "totalQuestions": len(correct_answers)
        }), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500