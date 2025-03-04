import os
from flask import Flask, request, jsonify
from flask_cors import CORS
import json
from wolframclient.evaluation import WolframCloudSession

consumer_key = os.environ.get('WOLFRAM_CONSUMER_KEY')
consumer_secret = os.environ.get('WOLFRAM_CONSUMER_SECRET')
session = WolframCloudSession(credentials=(consumer_key, consumer_secret))
session.start()

app = Flask(__name__)
CORS(app)

def wolfram_career_analysis(profile):
    query = f'''
    Module[{{data, analysis}},
        data = {json.dumps(profile)};
        analysis = WolframAlpha[
            "career recommendations for " <> data["education"] <> 
            " degree with " <> ToString[data["experience"]] <> 
            " years experience in " <> StringJoin[Riffle[data["skills"], ", "]], 
            {{{{{{'"Result"'", 1}}}}, "Plaintext"}}
        ];
        FinancialData[
            Entity["Country", data["location"]], 
            "AverageSalary", 
            {{{2020, 2023}}}
        ]
    ]
    '''
    return session.evaluate(query)

def skill_gap_analysis(user_skills, target_job):
    wolfram_skills = "{" + ", ".join(f'"{skill}"' for skill in user_skills) + "}"
    return session.evaluate(f'''
    SkillGapAnalysis[
        {wolfram_skills}, 
        JobData["{target_job}", "RequiredSkills"],
        "ComparisonMetric" -> "CompetencyLevel"
    ]
    ''')

def get_labor_data(country):
    return session.evaluate(f'''
    TimeSeries[
        LabourMarketData[
            Entity["Country", "{country}"], 
            {{"UnemploymentRate", "JobVacancies", "AverageWage"}}, 
            {{2010, 2023}}
        ]
    ]''')

@app.route('/recommend', methods=['POST'])
def recommend():
    try:
        profile = request.json
        
        career_query = f'''
        CareerRecommender[
            EducationLevel -> "{profile['education']}", 
            ExperienceYears -> {profile['experience']}, 
            KeySkills -> {json.dumps(profile['skills']).replace('[', '{').replace(']', '}')},
            GeoLocation -> Entity["Country", "{profile['location']}"],
            SalaryExpectation -> {profile['desiredSalary']}
        ]//Dataset'''
        
        careers = session.evaluate(career_query)
        
        roadmap_query = f'''
        LearningPathGenerator[
            RecommendedCareers -> {careers.to_wl()},
            AvailableLanguages -> {json.dumps(profile['languages']).replace('[', '{').replace(']', '}')},
            StudyPreference -> "Remote"
        ]'''
        
        roadmap = session.evaluate(roadmap_query)
        
        return jsonify({
            "careers": careers.to_dict(),
            "roadmap": roadmap.to_dict(),
            "opportunities": find_opportunities(profile)
        })
    
    except Exception as e:
        return jsonify({"error": str(e)}), 500

def find_opportunities(profile):
    return session.evaluate(f'''
    ExternalDataSources[
        "Scholarships", "RemoteJobs", "TrainingPrograms",
        Filter -> {{
            Country -> "{profile['location']}",
            Language -> {json.dumps(profile['languages']).replace('[', '{').replace(']', '}')},
            Deadline -> _?(# > Today() &),
            Salary -> _?(# >= {profile['desiredSalary']} &)
        }}
    ]
    ''')

if __name__ == '__main__':
    app.run(debug=True, port=8000)