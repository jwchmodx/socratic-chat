#!/usr/bin/env python3
"""Socratic Planning Chat - Claude API Web Interface"""

import os
from flask import Flask, render_template, request, jsonify, Response
from flask_cors import CORS
import anthropic

app = Flask(__name__)
CORS(app)

# Claude API client
client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))

SYSTEM_PROMPT = """# Socratic Planning

문제 인식 후 **나열 → 분류 → 재배열** 3단계로 기획을 진행한다.
핵심: **대립자(Devil's Advocate) 관점**에서 끊임없이 질문하고 비판한다.

## 시작
"어떤 문제/주제를 다루고 싶어?" 로 시작.

## STEP 1: 나열 (Enumerate)
- 사용자 먼저 나열하게 함
- AI도 추가 항목 제안
- 소크라테스 질문: "왜 그게 필요해?", "빠진 게 있을까?", "정말 이게 다야?"
- 대립자 비판: "잠깐, 이게 정말 필요해? 없으면 어떻게 돼?"

## STEP 2: 분류 (Classify)
- 분류 기준 제안 (중요도, 시간, 주체 등)
- 함께 분류
- 질문: "이건 왜 이 그룹이야?", "이 분류가 유용해?"

## STEP 3: 재배열 (Rearrange)
- 우선순위, 의존성 파악
- 구조화 제안
- 질문: "왜 이게 먼저야?", "이거 빼면?", "Plan B는?"

## 핵심 태도
1. 질문 > 답변
2. 대립자 역할 (항상 반대 관점)
3. 함께 작업 (일방적으로 하지 않음)
4. 불편함 유발 (쉽게 넘어가지 않음)

## 금지
- ❌ 사용자 대신 전부 나열/분류/재배열하기
- ❌ 비판 없이 "좋아요" 하기
- ❌ 단계 건너뛰기
- ❌ 질문 없이 결론 내리기

항상 한국어로 대화한다."""

conversation_history = []

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/chat', methods=['POST'])
def chat():
    global conversation_history
    
    user_message = request.json.get('message', '')
    if not user_message:
        return jsonify({'error': 'No message provided'}), 400
    
    conversation_history.append({
        "role": "user",
        "content": user_message
    })
    
    try:
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=2048,
            system=SYSTEM_PROMPT,
            messages=conversation_history
        )
        
        assistant_message = response.content[0].text
        conversation_history.append({
            "role": "assistant",
            "content": assistant_message
        })
        
        return jsonify({'response': assistant_message})
    
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/reset', methods=['POST'])
def reset():
    global conversation_history
    conversation_history = []
    return jsonify({'status': 'ok'})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5050))
    app.run(host='0.0.0.0', port=port, debug=False)
