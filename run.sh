#!/bin/bash
# Socratic Chat 실행 스크립트

# API 키 확인
if [ -z "$ANTHROPIC_API_KEY" ]; then
    echo "❌ ANTHROPIC_API_KEY 환경변수가 설정되지 않았습니다."
    echo ""
    echo "설정 방법:"
    echo "  export ANTHROPIC_API_KEY='your-api-key-here'"
    echo ""
    exit 1
fi

# 필요한 패키지 설치
pip install flask flask-cors anthropic -q

echo "🏛️ 소크라테스식 기획 도우미 시작..."
echo ""
echo "📍 로컬 접속: http://localhost:5050"
echo ""
echo "🌐 외부 접속이 필요하면:"
echo "   다른 터미널에서: ngrok http 5050"
echo ""

cd "$(dirname "$0")"
python3 app.py
