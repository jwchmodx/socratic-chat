#!/usr/bin/env python3
"""Socratic Planning Chat - Claude API Web Interface (OAuth 지원, 프로젝트 기반, 메모리+검색)"""

import os
import json
import re
import math
import httpx
import numpy as np
from datetime import datetime
from collections import Counter
from flask import Flask, render_template, request, jsonify, session, redirect
from flask_cors import CORS

# ===== 벡터 검색 (sentence-transformers) =====
_embedding_model = None

def get_embedding_model():
    """sentence-transformers 모델 lazy load"""
    global _embedding_model
    if _embedding_model is None:
        try:
            from sentence_transformers import SentenceTransformer
            _embedding_model = SentenceTransformer('paraphrase-multilingual-MiniLM-L12-v2')
            print("✅ Embedding model loaded")
        except Exception as e:
            print(f"⚠️ Embedding model failed: {e}")
    return _embedding_model

def get_embeddings(texts):
    """텍스트 리스트를 임베딩 벡터로 변환"""
    model = get_embedding_model()
    if model is None:
        return None
    return model.encode(texts, normalize_embeddings=True)

def vector_similarity(v1, v2):
    """코사인 유사도 (정규화된 벡터)"""
    return float(np.dot(v1, v2))

app = Flask(__name__)
app.secret_key = 'socratic-chat-secret-key-2026'

# 테스트 모드 (AI 호출 없이 Mock 응답)
TEST_MODE = os.environ.get('TEST_MODE', '').lower() == 'true'

# 대화 저장 경로
SAVE_BASE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "conversations")
os.makedirs(SAVE_BASE_DIR, exist_ok=True)

# 현재 사용자
current_user = None
# 현재 프로젝트
current_project = None
CORS(app)

# API 키/토큰 로드 (OAuth 우선)
def get_auth():
    oauth_file = os.path.expanduser("~/.openclaw/agents/main/agent/auth-profiles.json")
    if os.path.exists(oauth_file):
        with open(oauth_file) as f:
            data = json.load(f)
            profiles = data.get("profiles", {})
            for name, profile in profiles.items():
                if profile.get("provider") == "anthropic" and profile.get("type") == "oauth":
                    return profile.get("access"), True
    if os.environ.get("ANTHROPIC_API_KEY"):
        return os.environ.get("ANTHROPIC_API_KEY"), False
    key_file = os.path.expanduser("~/.config/anthropic/api_key")
    if os.path.exists(key_file):
        with open(key_file) as f:
            return f.read().strip(), False
    raise ValueError("No Anthropic credentials found")

TOKEN, IS_OAUTH = get_auth()
print(f"🔐 Auth mode: {'OAuth' if IS_OAUTH else 'API Key'}")

current_session = {
    "id": None,
    "topic": None,
    "started_at": None
}

def get_project_dir():
    global current_user
    user = current_user or "_anonymous"
    project = session.get('current_project', '_default')
    project_dir = os.path.join(SAVE_BASE_DIR, user, project)
    os.makedirs(project_dir, exist_ok=True)
    return project_dir

def get_memory_dir():
    """프로젝트의 memory/ 디렉토리"""
    mem_dir = os.path.join(get_project_dir(), "memory")
    os.makedirs(mem_dir, exist_ok=True)
    return mem_dir

def get_user_dir():
    global current_user
    user = current_user or "_anonymous"
    user_dir = os.path.join(SAVE_BASE_DIR, user)
    os.makedirs(user_dir, exist_ok=True)
    return user_dir

# ===== JSONL 대화 저장 =====

def append_to_jsonl(role, content, metadata=None):
    """JSONL에 한 턴 추가"""
    filepath = os.path.join(get_project_dir(), "conversation.jsonl")
    entry = {
        "timestamp": datetime.now().isoformat(),
        "role": role,
        "content": content,
        "project": session.get('current_project', '_default'),
        "user": current_user or "_anonymous",
    }
    if metadata:
        entry.update(metadata)
    with open(filepath, 'a', encoding='utf-8') as f:
        f.write(json.dumps(entry, ensure_ascii=False) + '\n')

def load_jsonl_messages():
    """JSONL에서 메시지 로드"""
    filepath = os.path.join(get_project_dir(), "conversation.jsonl")
    messages = []
    if os.path.exists(filepath):
        with open(filepath, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        entry = json.loads(line)
                        messages.append(entry)
                    except json.JSONDecodeError:
                        continue
    return messages

def get_conversation_messages():
    """대화용 메시지 (role + content만)"""
    entries = load_jsonl_messages()
    return [{"role": e["role"], "content": e["content"]} for e in entries if e["role"] in ("user", "assistant")]

# ===== 자동 요약 (메모리) =====

def save_step_memory(step_num, content):
    """STEP 완료 시 메모리 저장"""
    mem_dir = get_memory_dir()
    filenames = {1: "step1_items.md", 2: "step2_groups.md", 3: "step3_priorities.md"}
    filepath = os.path.join(mem_dir, filenames.get(step_num, f"step{step_num}.md"))
    
    project_name = session.get('current_project', '_default')
    header = f"# STEP {step_num} 결과 - {project_name}\n"
    header += f"_저장 시간: {datetime.now().strftime('%Y-%m-%d %H:%M')}_\n\n"
    
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(header + content + '\n')

def save_insights(content):
    """인사이트 저장"""
    filepath = os.path.join(get_memory_dir(), "insights.md")
    project_name = session.get('current_project', '_default')
    header = f"# 핵심 인사이트 - {project_name}\n"
    header += f"_저장 시간: {datetime.now().strftime('%Y-%m-%d %H:%M')}_\n\n"
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(header + content + '\n')

def check_auto_summary():
    """10턴마다 중간 요약 생성"""
    messages = get_conversation_messages()
    user_turns = [m for m in messages if m["role"] == "user"]
    turn_count = len(user_turns)
    
    if turn_count > 0 and turn_count % 10 == 0:
        # 중간 요약 생성
        try:
            summary_prompt = "지금까지 대화를 3-5줄로 요약해줘. 핵심 아이디어, 결정된 사항, 남은 질문 위주로."
            temp_msgs = messages + [{"role": "user", "content": summary_prompt}]
            summary = call_claude(temp_msgs)
            
            mem_dir = get_memory_dir()
            summary_file = os.path.join(mem_dir, "insights.md")
            
            with open(summary_file, 'a', encoding='utf-8') as f:
                f.write(f"\n---\n## 중간 요약 ({turn_count}턴, {datetime.now().strftime('%H:%M')})\n{summary}\n")
        except:
            pass

def extract_step_content(assistant_response, step_num):
    """AI 응답에서 STEP 관련 내용 추출"""
    if step_num == 2 and ("STEP 1 완료" in assistant_response or "나열된 항목" in assistant_response):
        save_step_memory(1, assistant_response)
    elif step_num == 3 and ("STEP 2 완료" in assistant_response or "분류 결과" in assistant_response):
        save_step_memory(2, assistant_response)
    
    if "최종 정리" in assistant_response or "핵심 인사이트" in assistant_response:
        save_insights(assistant_response)

def generate_project_report():
    """프로젝트 완료 시 자동 리포트 생성 (STEP 3 후)"""
    mem_dir = get_memory_dir()
    project_name = session.get('current_project', '_default')
    
    # 각 STEP 메모리 수집
    sections = []
    for step_file in ['step1_items.md', 'step2_groups.md', 'step3_priorities.md', 'insights.md']:
        filepath = os.path.join(mem_dir, step_file)
        if os.path.exists(filepath):
            with open(filepath, 'r', encoding='utf-8') as f:
                sections.append(f.read())
    
    # 대화에서 핵심 내용 추출
    messages = get_conversation_messages()
    user_msgs = [m['content'] for m in messages if m['role'] == 'user' and not m['content'].startswith('[')]
    
    report = f"# 📋 프로젝트 리포트: {project_name}\n"
    report += f"_생성 시간: {datetime.now().strftime('%Y-%m-%d %H:%M')}_\n"
    report += f"_총 대화 턴: {len(messages)}_\n\n"
    
    if sections:
        report += "## 진행 요약\n"
        report += "\n---\n".join(sections) + "\n\n"
    
    # AI로 핵심 결정사항/액션 아이템 추출 (TEST_MODE 아닐 때)
    if not TEST_MODE and messages:
        try:
            summary_prompt = """다음 대화를 분석해서 이 형식으로 정리해줘:

## 핵심 결정사항
- (결정된 것들)

## 다음 액션 아이템
- [ ] (해야 할 것들)

## 주요 인사이트
- (발견한 것들)

대화 내용만 기반으로 작성해. 간결하게."""
            temp_msgs = messages[-20:] + [{"role": "user", "content": summary_prompt}]
            ai_summary = call_claude(temp_msgs)
            report += "\n" + ai_summary + "\n"
        except:
            pass
    else:
        report += "## 핵심 결정사항\n- (AI 요약 비활성화)\n\n"
        report += "## 다음 액션 아이템\n- [ ] (수동 작성 필요)\n"
    
    # summary.md에 저장
    summary_path = os.path.join(mem_dir, "summary.md")
    with open(summary_path, 'w', encoding='utf-8') as f:
        f.write(report)
    
    return report

# ===== 이전 프로젝트 참조 감지 =====

PREVIOUS_REF_PATTERNS = [
    r'이전에', r'지난번', r'저번에', r'예전에', r'전에.*했', r'아까',
    r'다른\s*프로젝트', r'이전\s*프로젝트', r'지난\s*프로젝트',
    r'before', r'last\s*time', r'previously',
]

def detect_previous_reference(text):
    """이전 프로젝트 참조 감지"""
    for pattern in PREVIOUS_REF_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            return True
    return False

def find_related_projects(query):
    """관련 프로젝트 검색해서 컨텍스트 반환"""
    results = search_conversations(query, limit=5, mode='hybrid' if not TEST_MODE else 'tfidf')
    current_proj = session.get('current_project', '_default')
    
    # 다른 프로젝트의 결과만 필터
    other_projects = {}
    for r in results:
        proj = r.get('project', '')
        if proj != current_proj and proj not in other_projects:
            other_projects[proj] = r['preview']
    
    if not other_projects:
        return None
    
    context = "📎 **관련 이전 프로젝트 참고:**\n"
    for proj, preview in list(other_projects.items())[:3]:
        context += f"- **{proj}**: {preview[:100]}...\n"
    return context

# ===== 검색 기능 (TF-IDF) =====

def tokenize(text):
    """한국어+영어 간단 토크나이저"""
    # 한글 자소/영어/숫자 단위로 분리
    tokens = re.findall(r'[가-힣]+|[a-zA-Z]+|[0-9]+', text.lower())
    # 불용어 제거
    stopwords = {'은', '는', '이', '가', '을', '를', '에', '의', '로', '와', '과', '도', '에서', '으로',
                 '하고', '해서', '했', '한', '할', '하는', '있', '없', '것', '수', '등', '더', '좀',
                 'the', 'a', 'an', 'is', 'are', 'was', 'were', 'be', 'to', 'of', 'and', 'in', 'that'}
    return [t for t in tokens if t not in stopwords and len(t) > 1]

def compute_tfidf(documents):
    """TF-IDF 계산"""
    doc_tokens = [tokenize(doc) for doc in documents]
    N = len(documents)
    
    # DF 계산
    df = Counter()
    for tokens in doc_tokens:
        for token in set(tokens):
            df[token] += 1
    
    # TF-IDF 벡터
    tfidf_vectors = []
    for tokens in doc_tokens:
        tf = Counter(tokens)
        total = len(tokens) if tokens else 1
        vector = {}
        for token, count in tf.items():
            idf = math.log((N + 1) / (df.get(token, 0) + 1)) + 1
            vector[token] = (count / total) * idf
        tfidf_vectors.append(vector)
    
    return tfidf_vectors

def cosine_similarity(v1, v2):
    """코사인 유사도"""
    common = set(v1.keys()) & set(v2.keys())
    if not common:
        return 0.0
    dot = sum(v1[k] * v2[k] for k in common)
    norm1 = math.sqrt(sum(v ** 2 for v in v1.values()))
    norm2 = math.sqrt(sum(v ** 2 for v in v2.values()))
    if norm1 == 0 or norm2 == 0:
        return 0.0
    return dot / (norm1 * norm2)

def _collect_documents():
    """모든 프로젝트에서 문서 수집"""
    user_dir = get_user_dir()
    documents = []  # (text, metadata)
    
    if not os.path.exists(user_dir):
        return documents
    
    for project_name in os.listdir(user_dir):
        proj_dir = os.path.join(user_dir, project_name)
        if not os.path.isdir(proj_dir):
            continue
        
        # JSONL 대화 검색
        jsonl_file = os.path.join(proj_dir, "conversation.jsonl")
        if os.path.exists(jsonl_file):
            with open(jsonl_file, 'r', encoding='utf-8') as f:
                for i, line in enumerate(f):
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                        documents.append((entry["content"], {
                            "type": "conversation",
                            "project": project_name,
                            "role": entry.get("role", "unknown"),
                            "timestamp": entry.get("timestamp", ""),
                            "turn": i,
                        }))
                    except:
                        continue
        
        # 레거시 conversation.json도 검색
        json_file = os.path.join(proj_dir, "conversation.json")
        if os.path.exists(json_file) and not os.path.exists(jsonl_file):
            try:
                with open(json_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                for i, msg in enumerate(data.get("messages", [])):
                    documents.append((msg["content"], {
                        "type": "conversation",
                        "project": project_name,
                        "role": msg["role"],
                        "timestamp": data.get("started_at", ""),
                        "turn": i,
                    }))
            except:
                pass
        
        # memory/ 파일 검색
        mem_dir = os.path.join(proj_dir, "memory")
        if os.path.isdir(mem_dir):
            for mem_file in os.listdir(mem_dir):
                if mem_file.endswith('.md'):
                    filepath = os.path.join(mem_dir, mem_file)
                    try:
                        with open(filepath, 'r', encoding='utf-8') as f:
                            content = f.read()
                        documents.append((content, {
                            "type": "memory",
                            "project": project_name,
                            "file": mem_file,
                        }))
                    except:
                        continue
    
    return documents

def search_conversations(query, limit=20, mode='hybrid'):
    """모든 프로젝트에서 대화 검색 (하이브리드: TF-IDF + 벡터)"""
    documents = _collect_documents()
    if not documents:
        return []
    
    texts = [d[0] for d in documents]
    tfidf_scores = [0.0] * len(documents)
    vector_scores = [0.0] * len(documents)
    
    # TF-IDF 스코어
    if mode in ('tfidf', 'hybrid'):
        all_texts = [query] + texts
        vectors = compute_tfidf(all_texts)
        query_vector = vectors[0]
        for i in range(len(documents)):
            tfidf_scores[i] = cosine_similarity(query_vector, vectors[i + 1])
            # 키워드 부스트
            query_tokens = tokenize(query)
            text_lower = texts[i].lower()
            tfidf_scores[i] += sum(0.1 for t in query_tokens if t in text_lower)
    
    # 벡터 스코어
    if mode in ('vector', 'hybrid') and not TEST_MODE:
        try:
            embeddings = get_embeddings([query] + texts)
            if embeddings is not None:
                query_emb = embeddings[0]
                for i in range(len(documents)):
                    vector_scores[i] = max(0, vector_similarity(query_emb, embeddings[i + 1]))
        except Exception as e:
            print(f"⚠️ Vector search error: {e}")
    
    # 최종 스코어 (하이브리드: 가중 평균)
    scored = []
    for i, (text, meta) in enumerate(documents):
        if mode == 'tfidf':
            score = tfidf_scores[i]
        elif mode == 'vector':
            score = vector_scores[i]
        else:  # hybrid
            score = 0.4 * tfidf_scores[i] + 0.6 * vector_scores[i]
        
        if score > 0.01:
            preview = text[:200].replace('\n', ' ')
            scored.append({
                "score": round(score, 4),
                "tfidf_score": round(tfidf_scores[i], 4),
                "vector_score": round(vector_scores[i], 4),
                "preview": preview,
                "content": text[:500],
                **meta
            })
    
    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored[:limit]

# ===== 레거시 저장 호환 =====

def save_conversation(topic=None):
    """레거시: conversation.json 저장 (하위호환)"""
    global current_session
    messages = get_conversation_messages()
    
    if not messages:
        return None
    
    if not current_session["id"]:
        current_session["id"] = datetime.now().strftime("%Y%m%d_%H%M%S")
        current_session["started_at"] = datetime.now().isoformat()
    
    if not current_session["topic"] and topic:
        current_session["topic"] = topic
    elif not current_session["topic"] and len(messages) >= 2:
        first_user_msg = messages[0]["content"][:50]
        current_session["topic"] = first_user_msg.replace("\n", " ")
    
    # conversation.json도 계속 저장 (하위호환)
    filepath = os.path.join(get_project_dir(), "conversation.json")
    data = {
        "session_id": current_session["id"],
        "user": current_user,
        "project": session.get('current_project', '_default'),
        "topic": current_session["topic"],
        "started_at": current_session["started_at"],
        "saved_at": datetime.now().isoformat(),
        "message_count": len(messages),
        "messages": messages
    }
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    
    return filepath

conversation_history = []
collected_items = []

SYSTEM_PROMPT = """# 소크라테스식 기획 도우미

당신은 소크라테스식 질문과 비판을 통해 기획을 돕는 조력자입니다.

## 핵심 규칙

### 🎯 질문은 반드시 한 번에 하나씩!!!
⚠️ 가장 중요한 규칙: 한 응답에 질문은 딱 1개만!
- 절대 "A야? B는?" 이렇게 여러 질문 하지 마세요
- 질문 하나 → 사용자 답변 → 그 다음 질문
- 질문이 2개 이상이면 규칙 위반입니다

### 📋 3단계 프로세스 (사용자가 버튼으로 단계 전환)
**STEP 1: 나열** - 필요한 것들을 하나씩 꺼내기
**STEP 2: 분류** - 항목들을 그룹으로 묶기 (분류에 대해서만 질문!)  
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
...

━━━ 🔀 STEP 2: 분류 시작 ━━━
위 항목들을 어떤 기준으로 분류하면 좋을까?
```

사용자가 "[STEP3로 이동]"이라고 하면:
```
━━━ 📋 STEP 2 완료: 분류 결과 ━━━
[그룹A] - 항목들
...

━━━ 🎯 STEP 3: 재배열 시작 ━━━
이제 실행 순서를 정해보자.
```

사용자가 "[정리]"라고 하면:
```
📋 [주제명] 최종 정리
━━━ 나열된 항목들 ━━━
━━━ 분류 ━━━
━━━ 실행 순서 ━━━
━━━ 핵심 인사이트 ━━━
```

### STEP 2 분류 단계에서의 질문 예시
- "왜 이걸 이 그룹에 넣었어?"
- "이 그룹의 기준이 뭐야?"
- "빠진 항목 없어?"
- "이 두 그룹을 합치면 어때?"
- "이 항목은 다른 그룹에 더 맞지 않아?"

### 금지사항 (이거 하면 실패!)
- ❌ 여러 질문 한번에 하기 (가장 중요! 무조건 1개만!)
- ❌ "A야? 그리고 B는?" 이런 식으로 말하기
- ❌ 사용자 대신 다 정리해주기
- ❌ 자동으로 단계 전환하기
- ❌ "좋아요!"만 하고 넘어가기
- ❌ STEP 2에서 분류 외 다른 주제로 질문하기

항상 한국어로 대화합니다."""

def call_claude(messages):
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

# ===== 프로젝트 관련 API =====

@app.route('/projects', methods=['GET'])
def list_projects():
    user_dir = get_user_dir()
    projects = []
    
    if os.path.exists(user_dir):
        for name in sorted(os.listdir(user_dir)):
            proj_path = os.path.join(user_dir, name)
            if os.path.isdir(proj_path):
                conv_jsonl = os.path.join(proj_path, "conversation.jsonl")
                conv_json = os.path.join(proj_path, "conversation.json")
                info = {"name": name, "has_conversation": os.path.exists(conv_jsonl) or os.path.exists(conv_json)}
                
                # JSONL 우선
                if os.path.exists(conv_jsonl):
                    messages = []
                    with open(conv_jsonl, 'r', encoding='utf-8') as f:
                        for line in f:
                            if line.strip():
                                try:
                                    messages.append(json.loads(line.strip()))
                                except:
                                    pass
                    info["message_count"] = len(messages)
                    if messages:
                        info["topic"] = messages[0].get("content", "")[:50]
                        info["saved_at"] = messages[-1].get("timestamp", "")
                elif os.path.exists(conv_json):
                    try:
                        with open(conv_json, 'r', encoding='utf-8') as f:
                            data = json.load(f)
                            info["topic"] = data.get("topic", "")
                            info["message_count"] = data.get("message_count", 0)
                            info["saved_at"] = data.get("saved_at", "")
                    except:
                        pass
                
                # memory 파일 존재 여부
                mem_dir = os.path.join(proj_path, "memory")
                info["has_memory"] = os.path.isdir(mem_dir) and bool(os.listdir(mem_dir))
                
                projects.append(info)
    
    return jsonify(projects)

@app.route('/create_project', methods=['POST'])
def create_project():
    name = request.json.get('name', '').strip()
    if not name:
        return jsonify({'error': '프로젝트명을 입력하세요'}), 400
    
    safe_name = "".join(c for c in name if c.isalnum() or c in ('-', '_', ' ', 'ㄱ', 'ㄴ', 'ㄷ', 'ㄹ', 'ㅁ', 'ㅂ', 'ㅅ', 'ㅇ', 'ㅈ', 'ㅊ', 'ㅋ', 'ㅌ', 'ㅍ', 'ㅎ') or '\uAC00' <= c <= '\uD7A3').strip()
    if not safe_name:
        return jsonify({'error': '유효하지 않은 프로젝트명'}), 400
    
    proj_dir = os.path.join(get_user_dir(), safe_name)
    os.makedirs(proj_dir, exist_ok=True)
    os.makedirs(os.path.join(proj_dir, "memory"), exist_ok=True)
    
    session['current_project'] = safe_name
    return jsonify({'status': 'ok', 'name': safe_name})

@app.route('/select_project/<name>', methods=['POST'])
def select_project(name):
    global conversation_history, current_session
    
    proj_dir = os.path.join(get_user_dir(), name)
    if not os.path.isdir(proj_dir):
        return jsonify({'error': '프로젝트를 찾을 수 없습니다'}), 404
    
    session['current_project'] = name
    
    # JSONL 우선, 없으면 JSON
    jsonl_file = os.path.join(proj_dir, "conversation.jsonl")
    json_file = os.path.join(proj_dir, "conversation.json")
    
    if os.path.exists(jsonl_file):
        entries = []
        with open(jsonl_file, 'r', encoding='utf-8') as f:
            for line in f:
                if line.strip():
                    try:
                        entries.append(json.loads(line.strip()))
                    except:
                        pass
        conversation_history = [{"role": e["role"], "content": e["content"]} for e in entries if e["role"] in ("user", "assistant")]
        current_session = {
            "id": entries[0].get("timestamp", "")[:15].replace("-", "").replace(":", "").replace("T", "_") if entries else None,
            "topic": entries[0].get("content", "")[:50] if entries else None,
            "started_at": entries[0].get("timestamp") if entries else None
        }
    elif os.path.exists(json_file):
        with open(json_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        conversation_history = data.get("messages", [])
        current_session = {
            "id": data.get("session_id"),
            "topic": data.get("topic"),
            "started_at": data.get("started_at")
        }
    else:
        conversation_history = []
        current_session = {"id": None, "topic": None, "started_at": None}
    
    return jsonify({'status': 'ok', 'name': name, 'messages': conversation_history})

@app.route('/current_project', methods=['GET'])
def get_current_project():
    return jsonify({'project': session.get('current_project')})

@app.route('/delete_project/<name>', methods=['DELETE'])
def delete_project(name):
    import shutil
    proj_dir = os.path.join(get_user_dir(), name)
    if os.path.isdir(proj_dir):
        shutil.rmtree(proj_dir)
    if session.get('current_project') == name:
        session.pop('current_project', None)
    return jsonify({'status': 'ok'})

# ===== 테스트 데이터 정리 API =====

@app.route('/reset_test_data', methods=['POST'])
def reset_test_data():
    """테스트 사용자 데이터 삭제 (test_user, no_history_user_* 등)"""
    import shutil
    prefixes = request.json.get('prefixes', ['test_user', 'no_history_user_', 'TestUser', 'search_test_'])
    deleted = []
    if os.path.isdir(SAVE_BASE_DIR):
        for name in os.listdir(SAVE_BASE_DIR):
            if any(name == p or name.startswith(p) for p in prefixes):
                path = os.path.join(SAVE_BASE_DIR, name)
                if os.path.isdir(path):
                    shutil.rmtree(path)
                    deleted.append(name)
    return jsonify({'status': 'ok', 'deleted': deleted})

# ===== 검색 API =====

@app.route('/search', methods=['POST'])
def search():
    """대화 + 메모리 검색 (하이브리드: TF-IDF + 벡터)"""
    query = request.json.get('query', '').strip()
    mode = request.json.get('mode', 'hybrid')  # 'tfidf', 'vector', 'hybrid'
    if not query:
        return jsonify({'error': '검색어를 입력하세요'}), 400
    
    results = search_conversations(query, limit=20, mode=mode)
    return jsonify({'query': query, 'results': results, 'count': len(results), 'mode': mode})

# ===== 메모리 API =====

@app.route('/report', methods=['POST'])
def get_report():
    """프로젝트 리포트 생성/조회"""
    mem_dir = get_memory_dir()
    summary_path = os.path.join(mem_dir, "summary.md")
    
    force = request.json.get('force', False) if request.json else False
    
    if force or not os.path.exists(summary_path):
        report = generate_project_report()
        return jsonify({'report': report, 'generated': True})
    
    with open(summary_path, 'r', encoding='utf-8') as f:
        report = f.read()
    return jsonify({'report': report, 'generated': False})

@app.route('/memory', methods=['GET'])
def get_memory():
    """현재 프로젝트의 메모리 파일 목록"""
    mem_dir = get_memory_dir()
    files = {}
    for fname in os.listdir(mem_dir):
        if fname.endswith('.md'):
            filepath = os.path.join(mem_dir, fname)
            with open(filepath, 'r', encoding='utf-8') as f:
                files[fname] = f.read()
    return jsonify(files)

# ===== 마이그레이션 API =====

@app.route('/migrate', methods=['POST'])
def migrate_project():
    """현재 프로젝트의 conversation.json → conversation.jsonl 마이그레이션"""
    proj_dir = get_project_dir()
    json_file = os.path.join(proj_dir, "conversation.json")
    jsonl_file = os.path.join(proj_dir, "conversation.jsonl")
    
    if not os.path.exists(json_file):
        return jsonify({'status': 'skip', 'message': 'conversation.json 없음'})
    
    if os.path.exists(jsonl_file):
        return jsonify({'status': 'skip', 'message': 'conversation.jsonl 이미 존재'})
    
    with open(json_file, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    messages = data.get("messages", [])
    started_at = data.get("started_at", datetime.now().isoformat())
    
    with open(jsonl_file, 'w', encoding='utf-8') as f:
        for i, msg in enumerate(messages):
            entry = {
                "timestamp": started_at if i == 0 else datetime.now().isoformat(),
                "role": msg["role"],
                "content": msg["content"],
                "project": data.get("project", session.get('current_project', '_default')),
                "user": data.get("user", current_user or "_anonymous"),
            }
            f.write(json.dumps(entry, ensure_ascii=False) + '\n')
    
    return jsonify({'status': 'ok', 'migrated': len(messages)})

@app.route('/migrate_all', methods=['POST'])
def migrate_all():
    """모든 프로젝트 마이그레이션"""
    user_dir = get_user_dir()
    results = []
    
    for project_name in os.listdir(user_dir):
        proj_dir = os.path.join(user_dir, project_name)
        if not os.path.isdir(proj_dir):
            continue
        
        json_file = os.path.join(proj_dir, "conversation.json")
        jsonl_file = os.path.join(proj_dir, "conversation.jsonl")
        
        if not os.path.exists(json_file) or os.path.exists(jsonl_file):
            continue
        
        try:
            with open(json_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            messages = data.get("messages", [])
            started_at = data.get("started_at", datetime.now().isoformat())
            
            with open(jsonl_file, 'w', encoding='utf-8') as f:
                for i, msg in enumerate(messages):
                    entry = {
                        "timestamp": started_at if i == 0 else datetime.now().isoformat(),
                        "role": msg["role"],
                        "content": msg["content"],
                        "project": data.get("project", project_name),
                        "user": data.get("user", current_user or "_anonymous"),
                    }
                    f.write(json.dumps(entry, ensure_ascii=False) + '\n')
            
            # memory 디렉토리 생성
            os.makedirs(os.path.join(proj_dir, "memory"), exist_ok=True)
            
            results.append({"project": project_name, "migrated": len(messages)})
        except Exception as e:
            results.append({"project": project_name, "error": str(e)})
    
    return jsonify({'status': 'ok', 'results': results})

# ===== 기존 API (수정됨) =====

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/set_user', methods=['POST'])
def set_user():
    global current_user
    nickname = request.json.get('nickname', '').strip()
    if not nickname:
        return jsonify({'error': 'Nickname required'}), 400
    safe_nickname = "".join(c for c in nickname if c.isalnum() or c in ('-', '_', ' ') or '\uAC00' <= c <= '\uD7A3').strip()
    if not safe_nickname:
        return jsonify({'error': 'Invalid nickname'}), 400
    current_user = safe_nickname
    return jsonify({'status': 'ok', 'user': current_user})

@app.route('/get_user', methods=['GET'])
def get_user():
    return jsonify({'user': current_user})

@app.route('/kanban')
def kanban():
    return render_template('kanban.html')

@app.route('/get_items', methods=['GET'])
def get_items():
    return jsonify({'items': collected_items})

@app.route('/extract_items', methods=['POST'])
def extract_items():
    global collected_items, conversation_history
    if not conversation_history:
        return jsonify({'items': []})
    
    # 테스트 모드: Mock 응답
    if TEST_MODE:
        collected_items = ["테스트 항목 1", "테스트 항목 2", "테스트 항목 3"]
        return jsonify({'items': collected_items})
    
    extract_prompt = """지금까지 대화에서 나열된 모든 항목/아이디어/할 일을 추출해서 
JSON 배열로만 반환해줘. 다른 설명 없이 JSON 배열만.
예: ["항목1", "항목2", "항목3"]"""
    
    temp_history = conversation_history + [{"role": "user", "content": extract_prompt}]
    
    try:
        response = call_claude(temp_history)
        match = re.search(r'\[.*\]', response, re.DOTALL)
        if match:
            collected_items = json.loads(match.group())
        return jsonify({'items': collected_items})
    except Exception as e:
        return jsonify({'error': str(e), 'items': []}), 500

@app.route('/save_classification', methods=['POST'])
def save_classification():
    global conversation_history
    classification = request.json.get('classification', {})
    
    classification_text = "분류 결과:\n"
    for group, items in classification.items():
        classification_text += f"\n[{group}]\n"
        for item in items:
            classification_text += f"  - {item}\n"
    
    conversation_history.append({
        "role": "user",
        "content": f"[분류 완료]\n{classification_text}"
    })
    append_to_jsonl("user", f"[분류 완료]\n{classification_text}")
    save_conversation()
    
    # STEP 2 메모리 저장
    save_step_memory(2, classification_text)
    
    return jsonify({'status': 'ok'})

@app.route('/save_kanban', methods=['POST'])
def save_kanban():
    kanban_data = request.json
    kanban_file = os.path.join(get_project_dir(), 'kanban.json')
    with open(kanban_file, 'w', encoding='utf-8') as f:
        json.dump(kanban_data, f, ensure_ascii=False, indent=2)
    return jsonify({'status': 'ok'})

@app.route('/load_kanban', methods=['GET'])
def load_kanban():
    kanban_file = os.path.join(get_project_dir(), 'kanban.json')
    if os.path.exists(kanban_file):
        with open(kanban_file, 'r', encoding='utf-8') as f:
            return jsonify(json.load(f))
    return jsonify({'columns': [], 'cards': {}})

@app.route('/current_session_id', methods=['GET'])
def get_current_session_id():
    session_id = session.get('current_session_id') or current_session.get("id")
    return jsonify({'session_id': session_id})

@app.route('/chat', methods=['POST'])
def chat():
    global conversation_history
    user_message = request.json.get('message', '')
    if not user_message:
        return jsonify({'error': 'No message provided'}), 400
    
    conversation_history.append({"role": "user", "content": user_message})
    append_to_jsonl("user", user_message)
    
    # 이전 프로젝트 참조 감지
    prev_context = None
    if detect_previous_reference(user_message):
        prev_context = find_related_projects(user_message)
    
    # 테스트 모드: Mock 응답
    if TEST_MODE:
        assistant_message = "테스트 응답입니다. 무엇을 도와드릴까요?"
        if prev_context:
            assistant_message = prev_context + "\n\n" + assistant_message
        conversation_history.append({"role": "assistant", "content": assistant_message})
        append_to_jsonl("assistant", assistant_message)
        save_conversation()
        return jsonify({'response': assistant_message, 'prev_context': prev_context})
    
    try:
        # 이전 프로젝트 컨텍스트가 있으면 시스템 메시지에 추가
        msgs_to_send = list(conversation_history)
        if prev_context:
            msgs_to_send.insert(-1, {"role": "user", "content": f"[시스템 참고: {prev_context}]"})
            msgs_to_send.insert(-1, {"role": "assistant", "content": "네, 이전 프로젝트 내용을 참고하겠습니다."})
        
        assistant_message = call_claude(msgs_to_send)
        conversation_history.append({"role": "assistant", "content": assistant_message})
        append_to_jsonl("assistant", assistant_message)
        save_conversation()
        
        # 자동 요약 체크
        check_auto_summary()
        
        return jsonify({'response': assistant_message, 'prev_context': prev_context})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/reset', methods=['POST'])
def reset():
    global conversation_history, current_session
    if conversation_history:
        save_conversation()
    conversation_history = []
    current_session = {"id": None, "topic": None, "started_at": None}
    return jsonify({'status': 'ok'})

@app.route('/conversations', methods=['GET'])
def list_conversations():
    proj_dir = get_project_dir()
    
    # JSONL 우선
    jsonl_file = os.path.join(proj_dir, "conversation.jsonl")
    if os.path.exists(jsonl_file):
        entries = load_jsonl_messages()
        if entries:
            return jsonify([{
                "id": entries[0].get("timestamp", "")[:15].replace("-", "").replace(":", "").replace("T", "_"),
                "topic": entries[0].get("content", "")[:50],
                "started_at": entries[0].get("timestamp", ""),
                "message_count": len(entries)
            }])
    
    conv_file = os.path.join(proj_dir, "conversation.json")
    if os.path.exists(conv_file):
        with open(conv_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
            return jsonify([{
                "id": data.get("session_id"),
                "topic": data.get("topic", "제목 없음")[:50],
                "started_at": data.get("started_at"),
                "message_count": data.get("message_count", 0)
            }])
    return jsonify([])

@app.route('/conversations/<session_id>', methods=['GET'])
def get_conversation(session_id):
    filepath = os.path.join(get_project_dir(), "conversation.json")
    if not os.path.exists(filepath):
        return jsonify({'error': 'Not found'}), 404
    with open(filepath, 'r', encoding='utf-8') as f:
        data = json.load(f)
    return jsonify(data)

@app.route('/conversations/<session_id>/load', methods=['POST'])
def load_conversation(session_id):
    global conversation_history, current_session
    
    proj_dir = get_project_dir()
    
    # JSONL 우선
    jsonl_file = os.path.join(proj_dir, "conversation.jsonl")
    if os.path.exists(jsonl_file):
        entries = load_jsonl_messages()
        conversation_history = [{"role": e["role"], "content": e["content"]} for e in entries if e["role"] in ("user", "assistant")]
        current_session = {
            "id": session_id,
            "topic": entries[0].get("content", "")[:50] if entries else None,
            "started_at": entries[0].get("timestamp") if entries else None
        }
        session['current_session_id'] = session_id
        return jsonify({'status': 'ok', 'messages': conversation_history, 'session_id': session_id})
    
    filepath = os.path.join(proj_dir, "conversation.json")
    if not os.path.exists(filepath):
        return jsonify({'error': 'Not found'}), 404
    with open(filepath, 'r', encoding='utf-8') as f:
        data = json.load(f)
    conversation_history = data.get("messages", [])
    current_session = {
        "id": data.get("session_id"),
        "topic": data.get("topic"),
        "started_at": data.get("started_at")
    }
    session['current_session_id'] = current_session["id"]
    return jsonify({'status': 'ok', 'messages': conversation_history, 'session_id': current_session["id"]})

@app.route('/summarize', methods=['POST'])
def summarize():
    global conversation_history
    conversation_history.append({"role": "user", "content": "[정리]"})
    append_to_jsonl("user", "[정리]")
    try:
        assistant_message = call_claude(conversation_history)
        conversation_history.append({"role": "assistant", "content": assistant_message})
        append_to_jsonl("assistant", assistant_message)
        save_conversation()
        
        # 최종 정리 → 인사이트 저장
        save_insights(assistant_message)
        
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
    
    conversation_history.append({"role": "user", "content": command})
    append_to_jsonl("user", command)
    try:
        assistant_message = call_claude(conversation_history)
        conversation_history.append({"role": "assistant", "content": assistant_message})
        append_to_jsonl("assistant", assistant_message)
        save_conversation()
        
        # STEP 완료 시 메모리 저장
        extract_step_content(assistant_message, step)
        
        # STEP 3 완료 후 자동 리포트 생성
        report = None
        if step == 3:
            save_step_memory(3, assistant_message)
            try:
                report = generate_project_report()
            except Exception as e:
                print(f"⚠️ Report generation error: {e}")
        
        return jsonify({'response': assistant_message, 'step': step, 'report': report})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/logout')
def logout():
    global current_user, current_session, conversation_history
    current_user = None
    current_session = {"id": None, "topic": None, "started_at": None}
    conversation_history = []
    session.clear()
    return redirect('/')

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5050))
    print(f"🏛️ 소크라테스식 기획 도우미")
    print(f"📍 http://localhost:{port}")
    app.run(host='0.0.0.0', port=port, debug=False)
