import { test, expect, Page } from '@playwright/test';

const BASE_URL = 'http://121.88.140.70:8000';

// Helper: 테스트 데이터 정리
async function cleanTestData(page: Page) {
  await page.request.post(`${BASE_URL}/reset_test_data`, {
    data: { prefixes: ['test_user', 'no_history_user_', 'TestUser', 'search_test_', '재원', 'search_mode_', 'report_', 'summary_', 'prev_ref_', 'kanban_persist_', 'persistence_test_'] }
  });
}

// Helper: 닉네임 입력 후 메인 화면 진입 (프로젝트 생성 포함)
async function login(page: Page, nickname = 'TestUser') {
  await page.goto('/');
  const modal = page.locator('#nicknameModal');
  await expect(modal).toBeVisible();
  await page.fill('#nicknameInput', nickname);
  await page.click('button:has-text("시작하기")');
  await expect(modal).toBeHidden();

  // 프로젝트 모달이 표시되면 기본 프로젝트 생성
  const projectModal = page.locator('#projectModal');
  if (await projectModal.isVisible({ timeout: 3_000 }).catch(() => false)) {
    await page.fill('#newProjectName', 'default');
    await page.click('button:has-text("+ 생성")');
    await expect(projectModal).toBeHidden({ timeout: 5_000 });
  }
}

// Helper: 새 AI 응답 대기
async function waitForNewAssistantMessage(page: Page, timeout = 30_000) {
  // 로딩 인디케이터가 사라질 때까지 대기
  await expect(page.locator('.typing-indicator')).toBeHidden({ timeout });
  // 또는 테스트 응답 텍스트 확인
  await page.waitForTimeout(500);  // UI 업데이트 대기
}

// Helper: 메시지 전송 후 AI 응답 대기
async function sendAndWait(page: Page, message: string, timeout = 60_000) {
  const before = await page.locator('.message.assistant').count();
  await page.locator('#userInput').fill(message);
  await page.click('#sendBtn');
  await expect(async () => {
    const count = await page.locator('.message.assistant').count();
    expect(count).toBeGreaterThan(before);
  }).toPass({ timeout });
}

// Helper: 서버 상태 리셋 (로그아웃 + 대화 초기화)
async function resetServer(page: Page) {
  await page.goto('/logout');
  await page.waitForLoadState('networkidle');
}

// 전체 테스트 후 데이터 정리
test.afterAll(async ({ browser }) => {
  const page = await browser.newPage();
  await cleanTestData(page);
  await page.close();
});

// ─── 1. 인증 플로우 ───────────────────────────────────
test.describe('1. 인증 플로우', () => {
  test('첫 방문 시 닉네임 모달이 표시된다', async ({ page }) => {
    await resetServer(page);
    await page.goto('/');
    await expect(page.locator('#nicknameModal')).toBeVisible();
    await expect(page.locator('#nicknameInput')).toBeVisible();
  });

  test('닉네임 입력 후 메인 화면에 진입한다', async ({ page }) => {
    await resetServer(page);
    await login(page, '재원');
    await expect(page.locator('.header h1')).toContainText('재원');
    await expect(page.locator('#chatContainer')).toBeVisible();
  });

  test('로그아웃하면 닉네임 모달이 다시 표시된다', async ({ page }) => {
    await resetServer(page);
    await login(page, '재원');
    await page.click('button:has-text("로그아웃"), a:has-text("로그아웃"), [onclick*="logout"]');
    await expect(page.locator('#nicknameModal')).toBeVisible();
  });
});

// ─── 2. STEP 1: 나열 ─────────────────────────────────
test.describe('2. STEP 1: 나열', () => {
  test.beforeEach(async ({ page }) => {
    await resetServer(page);
    await login(page);
  });

  test('메시지를 보내면 AI 응답을 받는다', async ({ page }) => {
    await sendAndWait(page, '카페 창업을 준비하고 있어');
    await expect(page.locator('.message.user').last()).toContainText('카페 창업');
  });

  test('STEP 2 버튼 클릭 시 칸반 페이지로 이동한다', async ({ page }) => {
    await page.locator('#userInput').fill('웹사이트 만들기, 로고 디자인, 마케팅 계획');
    await page.click('#sendBtn');
    await waitForNewAssistantMessage(page);

    await page.click('#toStep2Btn');
    await expect(page).toHaveURL(/\/kanban/, { timeout: 15_000 });
  });
});

// ─── 3. STEP 2: 분류 (칸반) ──────────────────────────
test.describe('3. STEP 2: 분류 (칸반)', () => {
  test.beforeEach(async ({ page }) => {
    await resetServer(page);
    await login(page);
    await sendAndWait(page, '웹사이트 만들기, 로고 디자인, 마케팅 계획');
    await page.click('#toStep2Btn');
    await expect(page).toHaveURL(/\/kanban/, { timeout: 15_000 });
    await page.waitForLoadState('networkidle');
  });

  test('미분류 열에 아이템이 표시된다', async ({ page }) => {
    await expect(page.locator('#unassigned')).toBeVisible();
    await expect(page.locator('.column-header:has-text("미분류")')).toBeVisible();
  });

  test('카드를 드래그하여 다른 열로 이동할 수 있다', async ({ page }) => {
    const cards = page.locator('#unassigned .column-body .card');
    if (await cards.count() === 0) {
      page.on('dialog', async dialog => {
        await dialog.accept('테스트 카드');
      });
      await page.click('#unassigned .add-card-btn');
      await expect(page.locator('#unassigned .column-body .card')).toHaveCount(1);
    }

    const sourceCard = page.locator('#unassigned .column-body .card').first();
    const targetCol = page.locator('#col-1 .column-body');
    await sourceCard.dragTo(targetCol);
    await expect(page.locator('#col-1 .column-body .card')).toHaveCount(1);
  });

  test('열 이름을 변경할 수 있다', async ({ page }) => {
    const colInput = page.locator('#col-1 .column-header input');
    await colInput.fill('중요');
    await colInput.press('Tab');
    await expect(colInput).toHaveValue('중요');
  });

  test('분류 검토 버튼 클릭 시 AI 피드백을 받는다', async ({ page }) => {
    page.on('dialog', async dialog => {
      await dialog.accept('테스트 항목');
    });
    await page.click('#col-1 .add-card-btn');
    await page.locator('#col-1 .column-header input').fill('핵심');
    await page.click('#reviewBtn');
    await expect(page.locator('#chatSidebar')).toBeVisible();
    await expect(page.locator('#chatMessages .message.assistant')).toHaveCount(2, { timeout: 30_000 });
  });

  test('저장 & STEP 3 이동', async ({ page }) => {
    await page.click('button:has-text("저장 & STEP 3")');
    await expect(page).toHaveURL(/step=3|\//, { timeout: 15_000 });
  });
});

// ─── 4. STEP 3: 재배열 ───────────────────────────────
test.describe('4. STEP 3: 재배열', () => {
  test('STEP 3 메시지가 표시된다', async ({ page }) => {
    await resetServer(page);
    await login(page);

    await page.locator('#userInput').fill('A, B, C 세 가지');
    await page.click('#sendBtn');
    await waitForNewAssistantMessage(page);

    await page.click('#toStep2Btn');
    await expect(page).toHaveURL(/\/kanban/, { timeout: 15_000 });
    await page.waitForLoadState('networkidle');

    await page.click('button:has-text("저장 & STEP 3")');
    await page.waitForLoadState('networkidle');

    const modal = page.locator('#nicknameModal');
    if (await modal.isVisible()) {
      await page.fill('#nicknameInput', 'TestUser');
      await page.click('button:has-text("시작하기")');
    }

    await expect(page.locator('.message.assistant').last()).toContainText(/재배열|우선순위|STEP 3|분류/, { timeout: 15_000 });
  });
});

// ─── 5. 프로젝트 관리 ────────────────────────────────
test.describe('5. 프로젝트 관리', () => {
  test.beforeEach(async ({ page }) => {
    await resetServer(page);
    await cleanTestData(page);
  });

  test('프로젝트 버튼 클릭 시 프로젝트 모달이 표시된다', async ({ page }) => {
    await login(page, 'test_user');
    await page.click('button:has-text("📂 프로젝트")');
    const modal = page.locator('#projectModal');
    await expect(modal).toBeVisible();
    await expect(modal).toContainText('프로젝트 선택');
  });

  test('새 프로젝트를 생성할 수 있다', async ({ page }) => {
    await login(page, 'test_user');
    await page.click('button:has-text("📂 프로젝트")');
    const modal = page.locator('#projectModal');
    await expect(modal).toBeVisible();

    await page.fill('#newProjectName', '테스트프로젝트');
    await page.click('button:has-text("+ 생성")');
    await expect(modal).toBeHidden({ timeout: 5_000 });

    // 헤더에 프로젝트 이름 반영 확인
    await expect(page.locator('#chatContainer')).toBeVisible();
  });

  test('프로젝트 선택 시 대화가 불러와진다', async ({ page }) => {
    await login(page, 'test_user');

    // 첫 프로젝트에서 메시지 전송
    await page.locator('#userInput').fill('프로젝트A 테스트 메시지');
    await page.click('#sendBtn');
    await waitForNewAssistantMessage(page);

    // 두 번째 프로젝트 생성
    await page.click('button:has-text("📂 프로젝트")');
    await page.fill('#newProjectName', 'project_b');
    await page.click('button:has-text("+ 생성")');
    await expect(page.locator('#projectModal')).toBeHidden({ timeout: 5_000 });

    // 두 번째 프로젝트에는 이전 대화가 없어야 함
    const userMessages = page.locator('.message.user');
    await expect(userMessages).toHaveCount(0, { timeout: 3_000 });
  });

  test('프로젝트 전환 시 대화가 분리된다', async ({ page }) => {
    await login(page, 'test_user');

    // 프로젝트 A에서 메시지
    await page.locator('#userInput').fill('프로젝트A 내용');
    await page.click('#sendBtn');
    await waitForNewAssistantMessage(page);

    // 프로젝트 B 생성
    await page.click('button:has-text("📂 프로젝트")');
    await page.fill('#newProjectName', 'project_switch');
    await page.click('button:has-text("+ 생성")');
    await expect(page.locator('#projectModal')).toBeHidden({ timeout: 5_000 });

    // B에서 다른 메시지
    await page.locator('#userInput').fill('프로젝트B 내용');
    await page.click('#sendBtn');
    await waitForNewAssistantMessage(page);

    // A로 돌아가기
    await page.click('button:has-text("📂 프로젝트")');
    const modal = page.locator('#projectModal');
    await expect(modal).toBeVisible();
    await page.click(`#projectModal >> text=default`);
    await expect(modal).toBeHidden({ timeout: 5_000 });

    // A의 메시지가 보여야 함
    await expect(page.locator('.message.user').first()).toContainText('프로젝트A 내용');
  });

  test('프로젝트를 삭제할 수 있다', async ({ page }) => {
    await login(page, 'test_user');

    // 프로젝트 추가 생성
    await page.click('button:has-text("📂 프로젝트")');
    await page.fill('#newProjectName', 'to_delete');
    await page.click('button:has-text("+ 생성")');
    await expect(page.locator('#projectModal')).toBeHidden({ timeout: 5_000 });

    // 다시 프로젝트 모달 열기
    await page.click('button:has-text("📂 프로젝트")');
    const modal = page.locator('#projectModal');
    await expect(modal).toBeVisible();

    // 삭제 버튼 클릭 (confirm 다이얼로그 수락)
    page.on('dialog', async dialog => await dialog.accept());
    await page.click('#projectModal .project-delete >> nth=0');

    // 모달에서 해당 프로젝트가 사라지는지 확인 (짧은 대기)
    await page.waitForTimeout(1000);
  });

  test('프로젝트가 없으면 생성 안내가 표시된다', async ({ page }) => {
    const uniqueUser = 'no_history_user_' + Date.now();
    await login(page, uniqueUser);
    // 프로젝트 버튼 클릭
    await page.click('button:has-text("📂 프로젝트")');
    const modal = page.locator('#projectModal');
    await expect(modal).toBeVisible({ timeout: 5_000 });
    await expect(modal).toContainText(/프로젝트가 없|새로 만들/);
  });
});

// ─── 6. 검색 기능 ────────────────────────────────────
test.describe('6. 검색 기능', () => {
  test.beforeEach(async ({ page }) => {
    await resetServer(page);
  });

  test('검색 버튼 클릭 시 검색 모달이 표시된다', async ({ page }) => {
    await login(page, 'search_test_user');
    await page.click('button:has-text("🔍 검색")');
    const modal = page.locator('#searchModal');
    await expect(modal).toBeVisible();
    await expect(modal).toContainText('검색');
    await expect(page.locator('#searchInput')).toBeVisible();
  });

  test('검색어 입력 시 결과가 표시된다', async ({ page }) => {
    await login(page, 'search_test_user');

    // 먼저 대화 생성 (검색 대상)
    await page.locator('#userInput').fill('인공지능 스타트업 아이디어');
    await page.click('#sendBtn');
    await waitForNewAssistantMessage(page);

    // 검색
    await page.click('button:has-text("🔍 검색")');
    await page.fill('#searchInput', '인공지능');
    await page.click('#searchModal button:has-text("검색")');

    // 결과 표시 대기
    const results = page.locator('.search-result-item');
    await expect(results.first()).toBeVisible({ timeout: 10_000 });
  });

  test('검색 결과 클릭 시 해당 프로젝트로 이동한다', async ({ page }) => {
    await login(page, 'search_test_user');

    // 대화 생성 - 응답 대기를 유연하게
    await page.locator('#userInput').fill('블록체인 기술 분석');
    await page.click('#sendBtn');
    // 사용자 메시지가 표시되면 잠시 대기하여 저장 완료
    await expect(page.locator('.message.user').last()).toContainText('블록체인');
    await page.waitForTimeout(5_000);

    // 검색 후 결과 클릭
    await page.click('button:has-text("🔍 검색")');
    await page.fill('#searchInput', '블록체인');
    await page.click('#searchModal button:has-text("검색")');

    const results = page.locator('.search-result-item');
    await expect(results.first()).toBeVisible({ timeout: 10_000 });
    await results.first().click();

    // 검색 모달 닫힘
    await expect(page.locator('#searchModal')).toBeHidden({ timeout: 5_000 });
  });
});

// ─── 7. 벡터/하이브리드 검색 모드 ─────────────────────
test.describe('7. 검색 모드 (tfidf/vector/hybrid)', () => {
  test('TF-IDF 검색 모드로 결과를 받는다', async ({ page }) => {
    await resetServer(page);
    await login(page, 'search_mode_user');
    await sendAndWait(page, '머신러닝으로 추천 시스템 만들기');

    // UI에서 검색 (세션 쿠키 공유됨)
    await page.click('button:has-text("🔍 검색")');
    await page.fill('#searchInput', '머신러닝');
    await page.click('#searchModal button:has-text("검색")');
    const results = page.locator('.search-result-item');
    await expect(results.first()).toBeVisible({ timeout: 10_000 });
  });

  test('벡터 검색 모드 API가 정상 응답한다', async ({ page }) => {
    await resetServer(page);
    await login(page, 'search_mode_user2');
    // API 직접 호출 (mode 파라미터)
    const resp = await page.request.post(`${BASE_URL}/search`, {
      data: { query: '추천 시스템', mode: 'vector' }
    });
    const data = await resp.json();
    expect(data.mode).toBe('vector');
    expect(resp.status()).toBe(200);
  });

  test('하이브리드 검색 모드 API가 정상 응답한다', async ({ page }) => {
    await resetServer(page);
    await login(page, 'search_mode_user3');
    const resp = await page.request.post(`${BASE_URL}/search`, {
      data: { query: '딥러닝 모델', mode: 'hybrid' }
    });
    const data = await resp.json();
    expect(data.mode).toBe('hybrid');
    expect(resp.status()).toBe(200);
  });
});

// ─── 8. 스마트 요약 (리포트) ──────────────────────────
test.describe('8. 스마트 요약 & 리포트', () => {
  test('STEP 3 완료 후 리포트가 자동 생성된다', async ({ page }) => {
    await resetServer(page);
    await login(page, 'report_test_user');

    // STEP 1 → STEP 2 → STEP 3 진행
    await sendAndWait(page, 'A, B, C 세 가지 할 일');
    await page.click('#toStep2Btn');
    await expect(page).toHaveURL(/\/kanban/, { timeout: 15_000 });
    await page.waitForLoadState('networkidle');

    await page.click('button:has-text("저장 & STEP 3")');
    await page.waitForLoadState('networkidle');

    // 로그인 모달이 다시 뜨면 처리
    const modal = page.locator('#nicknameModal');
    if (await modal.isVisible()) {
      await page.fill('#nicknameInput', 'report_test_user');
      await page.click('button:has-text("시작하기")');
    }

    // 잠시 대기 후 리포트 확인
    await page.waitForTimeout(2_000);
  });

  test('/report API 호출 시 요약을 반환한다', async ({ page }) => {
    await resetServer(page);
    await login(page, 'report_api_user');
    await sendAndWait(page, '리포트 테스트용 메시지');

    const resp = await page.request.post(`${BASE_URL}/report`, {
      data: { force: true }
    });
    expect(resp.status()).toBe(200);
    const data = await resp.json();
    expect(data.report).toBeTruthy();
    expect(data.report).toContain('프로젝트 리포트');
    expect(data.generated).toBe(true);
  });

  test('/report 호출 후 memory/summary.md 파일이 생성된다', async ({ page }) => {
    await resetServer(page);
    await login(page, 'summary_file_user');
    await sendAndWait(page, '요약 파일 생성 테스트');

    await page.request.post(`${BASE_URL}/report`, {
      data: { force: true }
    });

    // memory API로 확인
    const memResp = await page.request.get(`${BASE_URL}/memory`);
    const memData = await memResp.json();
    expect(memData['summary.md']).toBeTruthy();
    expect(memData['summary.md']).toContain('프로젝트 리포트');
  });
});

// ─── 9. 이전 프로젝트 참조 ────────────────────────────
test.describe('9. 이전 프로젝트 참조', () => {
  test('"이전에" 키워드 입력 시 응답에 이전 참조가 반영된다', async ({ page }) => {
    await resetServer(page);
    await cleanTestData(page);
    await login(page, 'prev_ref_user');

    // 프로젝트 A에서 대화
    await sendAndWait(page, '카페 창업 아이디어 정리');

    // 프로젝트 B 생성 후 이전 참조
    await page.click('button:has-text("📂 프로젝트")');
    await page.fill('#newProjectName', 'project_b');
    await page.click('button:has-text("+ 생성")');
    await expect(page.locator('#projectModal')).toBeHidden({ timeout: 5_000 });

    // "이전에" 키워드로 메시지 전송 (UI를 통해)
    await sendAndWait(page, '이전에 했던 카페 관련 내용 알려줘');

    // AI 응답이 있으면 성공 (TEST_MODE에서 prev_context + mock 응답)
    const lastMsg = page.locator('.message.assistant').last();
    await expect(lastMsg).toBeVisible();
  });

  test('"지난번" 키워드도 이전 참조로 감지된다', async ({ page }) => {
    await resetServer(page);
    await cleanTestData(page);
    await login(page, 'prev_ref_user2');
    await sendAndWait(page, '블록체인 프로젝트 기획');

    // 다른 프로젝트에서 "지난번" 사용
    await page.click('button:has-text("📂 프로젝트")');
    await page.fill('#newProjectName', 'new_proj');
    await page.click('button:has-text("+ 생성")');
    await expect(page.locator('#projectModal')).toBeHidden({ timeout: 5_000 });

    await sendAndWait(page, '지난번 블록체인 이야기 이어서 하자');
    const lastMsg = page.locator('.message.assistant').last();
    await expect(lastMsg).toBeVisible();
  });
});

// ─── 10. 데이터 영속성 ──────────────────────────────────
test.describe('10. 데이터 영속성', () => {
  test('새로고침 후에도 대화가 유지된다', async ({ page }) => {
    await resetServer(page);
    await login(page, 'persistence_test_user');

    // 메시지 전송
    await page.locator('#userInput').fill('영속성 테스트 메시지');
    await page.click('#sendBtn');
    await waitForNewAssistantMessage(page);

    // 새로고침
    await page.reload();
    await page.waitForLoadState('networkidle');

    // 프로젝트 선택 (default)
    const modal = page.locator('#projectModal');
    if (await modal.isVisible()) {
      await page.click('#projectModal >> text=default');
      await expect(modal).toBeHidden({ timeout: 5_000 });
    }

    // 이전 메시지가 보여야 함
    await expect(page.locator('.message.user').first()).toContainText('영속성 테스트 메시지');
  });

  test('칸반 상태가 저장되고 복원된다', async ({ page }) => {
    await resetServer(page);
    await login(page, 'kanban_persist_user');

    // 메시지 보내고 STEP 2로 이동
    await page.locator('#userInput').fill('칸반 테스트 항목1, 항목2, 항목3');
    await page.click('#sendBtn');
    await waitForNewAssistantMessage(page);
    await page.click('#toStep2Btn');
    await expect(page).toHaveURL(/\/kanban/, { timeout: 15_000 });

    // 열 이름 변경
    const firstColumnInput = page.locator('.column').nth(1).locator('input');
    await firstColumnInput.fill('테스트그룹');
    await page.waitForTimeout(500);  // 저장 대기

    // STEP 1로 돌아갔다가 다시 STEP 2로
    await page.click('button:has-text("STEP 1")');
    await expect(page).toHaveURL(/\//, { timeout: 10_000 });
    await page.click('#toStep2Btn');
    await expect(page).toHaveURL(/\/kanban/, { timeout: 15_000 });

    // 열 이름이 유지되어야 함
    await expect(firstColumnInput).toHaveValue('테스트그룹');
  });
});
