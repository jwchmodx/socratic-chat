#!/usr/bin/env python3
"""Socratic Planning Chat - Claude API Web Interface (OAuth 지원)"""

import os
import json
import httpx
from flask import Flask, render_template, request, jsonify
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

# API 키/토큰 로드 (OAuth 우선)
def get_auth():
    """
    Returns: (token, is_oauth)
    우선순위:
    1. OpenClaw OAuth 프로필 (~/.openclaw/agents/main/agent/auth-profiles.json)
    2. 환경변수 ANTHROPIC_API_KEY
    3. 설정 파일 ~/.config/anthropic/api_key
    """
    # 1. OpenClaw OAuth
    oauth_file = os.path.expanduser("~/.openclaw/agents/main/agent/auth-profiles.json")
    if os.path.exists(oauth_file):
        with open(oauth_file) as f:
            data = json.load(f)
            profiles = data.get("profiles", {})
            for name, profile in profiles.items():
                if profile.get("provider") == "anthropic" and profile.get("type") == "oauth":
                    return profile.get("access"), True
    
    # 2. 환경변수
    if os.environ.get("ANTHROPIC_API_KEY"):
        return os.environ.get("ANTHROPIC_API_KEY"), False
    
    # 3. 설정 파일
    key_file = os.path.expanduser("~/.config/anthropic/api_key")
    if os.path.exists(key_file):
        with open(key_file) as f:
            return f.read().strip(), False
    
    raise ValueError("No Anthropic credentials found")

TOKEN, IS_OAUTH = get_auth()
print(f"🔐 Auth mode: {'OAuth' if IS_OAUTH else 'API Key'}")

SYSTEM_PROMPT = """# 소크라테스식 기획 도우미

당신은 소크라테스식 질문과 비판을 통해 기획을 돕는 조력자입니다.

## 핵심 규칙

### 🎯 질문은 반드시 한 번에 하나씩!
- 절대 여러 질문을 한 번에 하지 마세요
- 하나의 질문 → 답변 대기 → 다음 질문

### 📋 3단계 프로세스 (사용자가 버튼으로 단계 전환)
**STEP 1: 나열** - 필요한 것들을 하나씩 꺼내기
**STEP 2: 분류** - 항목들을 그룹으로 묶기  
**STEP 3: 재배열** - 실행 순서/구조 만들기

### 🔄 진행 방식
1. 먼저 "어떤 문제/주제를 다루고 싶어?"로 시작
2. STEP 1에서는 계속 나열하게 유도
3. 사용자가 답하면 추가 제안 + 비판적 질문
4. **단계 전환은 사용자가 버튼으로 함** (자동으로 넘어가지 말 것!)

### 😈 대립자 역할
- 항상 반대 관점에서 질문
- "정말?", "왜?", "없으면 어떻게 돼?" 
- 쉽게 넘어가지 않기

### 📊 단계 전환 시 응답 형식

사용자가 "[STEP2로 이동]"이라고 하면:
```
━━━ 📋 STEP 1 완료: 나열된 항목들 ━━━
1. 항목1
2. 항목2
3. 항목3
...

━━━ 🔀 STEP 2: 분류 시작 ━━━
위 항목들을 어떤 기준으로 분류하면 좋을까?

예를 들어:
- 중요도 (필수/선택)
- 시간 (즉시/나중)
- 성격 (행동/자원/조건)

어떤 기준이 좋을 것 같아?
```

사용자가 "[STEP3로 이동]"이라고 하면:
```
━━━ 📋 STEP 2 완료: 분류 결과 ━━━
[그룹A]
  - 항목1
  - 항목2
[그룹B]
  - 항목3
...

━━━ 🎯 STEP 3: 재배열 시작 ━━━
이제 실행 순서를 정해보자.
뭐부터 해야 할 것 같아?
```

사용자가 "[정리]"라고 하면:
```
📋 [주제명] 최종 정리

━━━ 나열된 항목들 ━━━
• 항목들...

━━━ 분류 ━━━
[그룹A] - 항목들
[그룹B] - 항목들

━━━ 실행 순서 ━━━
1. 첫 번째
2. 두 번째
...

━━━ 핵심 인사이트 ━━━
• 대화에서 나온 깨달음
```

### 금지사항
- ❌ 여러 질문 한번에 하기
- ❌ 사용자 대신 다 정리해주기
- ❌ 자동으로 단계 전환하기 (사용자 버튼 대기!)
- ❌ "좋아요!"만 하고 넘어가기

항상 한국어로 대화합니다."""

conversation_history = []

def call_claude(messages):
    """Claude API 호출 (OAuth/API Key 자동 처리)"""
    headers = {
        'Content-Type': 'application/json',
        'anthropic-version': '2023-06-01',
    }
    
    if IS_OAUTH:
        headers['Authorization'] = f'Bearer {TOKEN}'
        headers['anthropic-beta'] = 'oauth-2025-04-20'
    else:
        headers['x-api-key'] = TOKEN
    
    data = {
        'model': 'claude-sonnet-4-20250514',
        'max_tokens': 2048,
        'system': SYSTEM_PROMPT,
        'messages': messages
    }
    
    response = httpx.post(
        'https://api.anthropic.com/v1/messages',
        headers=headers,
        json=data,
        timeout=60
    )
    
    if response.status_code != 200:
        raise Exception(f"API Error: {response.status_code} - {response.text}")
    
    return response.json()['content'][0]['text']

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
        assistant_message = call_claude(conversation_history)
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

@app.route('/summarize', methods=['POST'])
def summarize():
    global conversation_history
    
    conversation_history.append({
        "role": "user",
        "content": "[정리]"
    })
    
    try:
        assistant_message = call_claude(conversation_history)
        conversation_history.append({
            "role": "assistant",
            "content": assistant_message
        })
        
        return jsonify({'response': assistant_message})
    
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/next_step', methods=['POST'])
def next_step():
    global conversation_history
    
    step = request.json.get('step', 2)
    
    if step == 2:
        command = "[STEP2로 이동]"
    elif step == 3:
        command = "[STEP3로 이동]"
    else:
        return jsonify({'error': 'Invalid step'}), 400
    
    conversation_history.append({
        "role": "user",
        "content": command
    })
    
    try:
        assistant_message = call_claude(conversation_history)
        conversation_history.append({
            "role": "assistant",
            "content": assistant_message
        })
        
        return jsonify({'response': assistant_message, 'step': step})
    
    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5050))
    print(f"🏛️ 소크라테스식 기획 도우미")
    print(f"📍 http://localhost:{port}")
    app.run(host='0.0.0.0', port=port, debug=False)
