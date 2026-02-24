#!/usr/bin/env python3
"""기존 대화 파일들을 프로젝트 폴더 구조로 마이그레이션"""
import os, json, shutil

BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "conversations")

for user in os.listdir(BASE):
    user_dir = os.path.join(BASE, user)
    if not os.path.isdir(user_dir):
        continue
    
    # 기존 json 파일들 찾기
    json_files = [f for f in os.listdir(user_dir) if f.endswith('.json') and os.path.isfile(os.path.join(user_dir, f))]
    if not json_files:
        continue
    
    # 이미 프로젝트 폴더 구조인지 확인
    has_subdirs = any(os.path.isdir(os.path.join(user_dir, d)) for d in os.listdir(user_dir))
    
    # 대화 파일 그룹핑 (session_id 기반)
    sessions = {}
    kanban_files = {}
    other_files = []
    
    for f in json_files:
        filepath = os.path.join(user_dir, f)
        if f.endswith('_kanban.json') or f == '_kanban_state.json':
            # kanban 파일
            session_id = f.replace('_kanban.json', '')
            kanban_files[session_id] = filepath
        elif f.startswith('_'):
            other_files.append(filepath)
        else:
            session_id = f.replace('.json', '')
            sessions[session_id] = filepath
    
    if not sessions and not kanban_files:
        continue
    
    print(f"\n📁 사용자: {user}")
    
    # 각 세션을 프로젝트 폴더로 이동
    for session_id, conv_path in sessions.items():
        try:
            with open(conv_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            topic = data.get('topic', session_id)[:30] or session_id
            # 안전한 폴더명
            safe_topic = "".join(c for c in topic if c.isalnum() or c in ('-', '_', ' ') or '\uAC00' <= c <= '\uD7A3').strip()
            if not safe_topic:
                safe_topic = session_id
            
            proj_dir = os.path.join(user_dir, safe_topic)
            os.makedirs(proj_dir, exist_ok=True)
            
            # conversation.json으로 복사
            shutil.copy2(conv_path, os.path.join(proj_dir, "conversation.json"))
            print(f"  ✅ {session_id} → {safe_topic}/conversation.json")
            
            # 대응하는 kanban 파일이 있으면 복사
            if session_id in kanban_files:
                shutil.copy2(kanban_files[session_id], os.path.join(proj_dir, "kanban.json"))
                print(f"  ✅ {session_id}_kanban → {safe_topic}/kanban.json")
            
            # 원본 삭제
            os.remove(conv_path)
            if session_id in kanban_files:
                os.remove(kanban_files[session_id])
                
        except Exception as e:
            print(f"  ❌ {session_id} 실패: {e}")
    
    # _default kanban 처리
    for key, path in kanban_files.items():
        if os.path.exists(path) and key not in sessions:
            print(f"  ⏭️ 남은 칸반 파일: {os.path.basename(path)}")
    
    # 기타 파일 정리
    for path in other_files:
        if os.path.exists(path):
            fname = os.path.basename(path)
            print(f"  ⏭️ 기타 파일: {fname}")

print("\n✅ 마이그레이션 완료!")
