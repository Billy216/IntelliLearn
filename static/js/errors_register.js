// ============================================================
//  errors_register.js - 错题本（带模态框）
// ============================================================

// ===== 兜底模拟题库数据（接口失败时使用） =====
const FALLBACK_QUESTIONS = [
    // ===== 高等数学 (6道) =====
    { id: 1, subject: '高等数学', grade: '大一', question: '求极限 lim(x→0) (sin x)/x', answer: 'lim(x→0) (sin x)/x = 1。这是重要极限。' },
    { id: 2, subject: '高等数学', grade: '大一', question: '求导数：y = x³ + 2x² - 5x + 1', answer: "y' = 3x² + 4x - 5。使用幂函数求导法则。" },
    { id: 3, subject: '高等数学', grade: '大二', question: '计算定积分 ∫₀¹ x² dx', answer: '∫₀¹ x² dx = [x³/3]₀¹ = 1/3。' },
    { id: 4, subject: '高等数学', grade: '大一', question: '判断级数 ∑(1/n²) 的收敛性', answer: '∑(1/n²) 收敛。这是 p-级数，p=2>1。' },
    { id: 5, subject: '高等数学', grade: '大二', question: '求微分方程 dy/dx = 2x 的通解', answer: 'y = x² + C。分离变量法求解。' },
    { id: 6, subject: '高等数学', grade: '大一', question: '求函数 f(x) = x² 在 x=1 处的切线方程', answer: 'y = 2x - 1。切线斜率 k = f\'(1) = 2，过点 (1,1)。' },
    
    // ===== 线性代数 (5道) =====
    { id: 7, subject: '线性代数', grade: '大一', question: '计算矩阵 A = [[1,2],[3,4]] 的行列式', answer: 'det(A) = 1×4 - 2×3 = 4-6 = -2。' },
    { id: 8, subject: '线性代数', grade: '大二', question: '求矩阵 A = [[1,2,3],[4,5,6],[7,8,9]] 的秩', answer: 'r(A) = 2。因为三阶矩阵的行列式为 0，但存在二阶非零子式。' },
    { id: 9, subject: '线性代数', grade: '大一', question: '判断向量组 α₁=(1,0), α₂=(0,1) 是否线性相关', answer: '线性无关。因为不存在非零常数 k₁, k₂ 使 k₁α₁ + k₂α₂ = 0。' },
    { id: 10, subject: '线性代数', grade: '大二', question: '求解线性方程组：x + y = 3, 2x - y = 0', answer: 'x = 1, y = 2。用消元法求解。' },
    { id: 11, subject: '线性代数', grade: '大一', question: '计算矩阵乘法：[[1,2],[3,4]] × [[5,6],[7,8]]', answer: '[[19,22],[43,50]]。按矩阵乘法规则计算。' },
    
    // ===== 概率论 (5道) =====
    { id: 12, subject: '概率论', grade: '大二', question: '同时掷两枚骰子，求点数和为 7 的概率', answer: 'P = 6/36 = 1/6。共有 6 种组合(1,6),(2,5),(3,4),(4,3),(5,2),(6,1)。' },
    { id: 13, subject: '概率论', grade: '大二', question: '设随机变量 X ~ N(0,1)，求 P(X > 1.96)', answer: 'P(X > 1.96) = 0.025。标准正态分布的上尾概率。' },
    { id: 14, subject: '概率论', grade: '大一', question: '抛一枚硬币三次，求恰好出现两次正面的概率', answer: 'P = C(3,2)×(1/2)³ = 3/8。' },
    { id: 15, subject: '概率论', grade: '大二', question: '某产品合格率为 0.9，随机抽取 10 件，求恰有 8 件合格的概率', answer: 'P = C(10,8)×0.9⁸×0.1² ≈ 0.1937。二项分布。' },
    { id: 100, subject: '概率论', grade: '大三', question: '设 X 服从泊松分布 P(λ)，求 E(X) 和 D(X)', answer: 'E(X) = λ，D(X) = λ。泊松分布的期望和方差都等于参数 λ。' },
    
    // ===== 大学物理 (5道) =====
    { id: 16, subject: '大学物理', grade: '大二', question: '一质点做简谐运动，振幅为 A，周期为 T，求其最大速度', answer: 'v_max = 2πA/T。简谐运动的最大速度在平衡位置。' },
    { id: 17, subject: '大学物理', grade: '大一', question: '一物体从静止开始自由下落 5s，求下落高度', answer: 'h = (1/2)gt² = (1/2)×10×25 = 125m。' },
    { id: 18, subject: '大学物理', grade: '大二', question: '两个点电荷相距 r，求它们之间的库仑力', answer: 'F = kq₁q₂/r²。库仑定律。' },
    { id: 19, subject: '大学物理', grade: '大一', question: '匀速圆周运动的向心加速度公式是什么？', answer: 'a = v²/r = ω²r。向心加速度公式。' },
    { id: 20, subject: '大学物理', grade: '大二', question: '推导理想气体的状态方程 PV = nRT', answer: '由玻意耳定律、查理定律、盖-吕萨克定律推导。PV = nRT。' },
    
    // ===== 化学 (4道) =====
    { id: 21, subject: '化学', grade: '大一', question: '写出化学反应方程式：Fe + CuSO₄ → ?', answer: 'Fe + CuSO₄ = FeSO₄ + Cu。置换反应。' },
    { id: 22, subject: '化学', grade: '大二', question: '计算 pH = 3 的盐酸溶液中 H⁺ 的浓度', answer: '[H⁺] = 10⁻³ mol/L。pH = -lg[H⁺]。' },
    { id: 23, subject: '化学', grade: '大一', question: '水的化学式是什么？', answer: 'H₂O。水分子由一个氧原子和两个氢原子组成。' },
    { id: 24, subject: '化学', grade: '大二', question: '什么是氧化还原反应？请举例说明。', answer: '氧化还原反应是电子转移的反应。例：2Mg + O₂ = 2MgO。' },
    
    // ===== 生物学 (4道) =====
    { id: 25, subject: '生物学', grade: '大二', question: 'DNA 的复制方式是什么？', answer: '半保留复制。DNA 双链分开，各以一条链为模板合成新链。' },
    { id: 26, subject: '生物学', grade: '大一', question: '细胞膜的主要成分是什么？', answer: '磷脂双分子层和蛋白质。细胞膜的基本骨架是磷脂双分子层。' },
    { id: 27, subject: '生物学', grade: '大二', question: '简述光合作用的光反应与暗反应的关系。', answer: '光反应为暗反应提供 ATP 和 [H]，暗反应为光反应提供 ADP 和 Pi。' },
    { id: 28, subject: '生物学', grade: '大一', question: '什么是基因？基因在染色体上的位置叫什么？', answer: '基因是遗传的基本单位。位置在染色体上叫基因座。' },
    
    // ===== 计算机科学 (5道) =====
    { id: 29, subject: '计算机科学', grade: '大一', question: '什么是时间复杂度？请分析冒泡排序的时间复杂度。', answer: '时间复杂度描述算法运行时间与输入规模的关系。冒泡排序 O(n²)。' },
    { id: 30, subject: '计算机科学', grade: '大二', question: '写出二叉树的三种遍历方式及其代码实现。', answer: '前序：根-左-右；中序：左-根-右；后序：左-右-根。' },
    { id: 31, subject: '计算机科学', grade: '大一', question: '什么是变量？在 Python 中如何定义变量？', answer: '变量是存储数据的容器。Python: x = 5。' },
    { id: 32, subject: '计算机科学', grade: '大二', question: '解释什么是递归，并给出一个简单的递归例子。', answer: '递归是函数调用自身。例：求 n! = n×(n-1)!' },
    { id: 33, subject: '计算机科学', grade: '大三', question: '什么是死锁？产生死锁的四个必要条件是什么？', answer: '死锁是多个进程相互等待资源。必要条件：互斥、占有等待、不可剥夺、循环等待。' },
    
    // ===== 经济学 (4道) =====
    { id: 34, subject: '经济学', grade: '大一', question: '什么是需求定律？请用日常生活中的例子说明。', answer: '需求定律：价格上升，需求量下降。例：商场打折销量增加。' },
    { id: 35, subject: '经济学', grade: '大二', question: '解释 GDP 的含义，并说明其计算方法。', answer: 'GDP 是国内生产总值，核算一定时期内生产的最终产品价值。' },
    { id: 36, subject: '经济学', grade: '大二', question: '分析通货膨胀的成因及其对经济的影响。', answer: '通胀由货币过多或成本上升引起，会导致购买力下降。' },
    { id: 37, subject: '经济学', grade: '大一', question: '什么是边际效用递减规律？', answer: '边际效用递减：随着消费量增加，每单位商品带来的效用递减。' },
    
    // ===== 管理学 (4道) =====
    { id: 38, subject: '管理学', grade: '大一', question: '管理的四大基本职能是什么？', answer: '计划、组织、领导、控制。' },
    { id: 39, subject: '管理学', grade: '大二', question: '马斯洛需求层次理论包含哪些内容？', answer: '生理需求、安全需求、社交需求、尊重需求、自我实现。' },
    { id: 40, subject: '管理学', grade: '大三', question: '什么是 SWOT 分析？如何在实际管理中使用？', answer: 'SWOT 分析优势、劣势、机会、威胁。用于战略决策。' },
    { id: 41, subject: '管理学', grade: '大二', question: '简述泰勒的科学管理理论的核心思想。', answer: '泰勒科学管理强调标准化、分工和效率。' },
    
    // ===== 法学 (4道) =====
    { id: 42, subject: '法学', grade: '大一', question: '法的基本特征是什么？', answer: '法的基本特征：规范性、国家强制性、普遍性、程序性。' },
    { id: 43, subject: '法学', grade: '大二', question: '分析我国宪法的基本原则。', answer: '我国宪法原则：人民主权、法治、人权保障、权力制约。' },
    { id: 44, subject: '法学', grade: '大一', question: '什么是法律关系？构成要素有哪些？', answer: '法律关系是法律规范调整社会关系形成的权利义务关系。' },
    { id: 45, subject: '法学', grade: '大二', question: '简述罪刑法定原则的含义。', answer: '罪刑法定：法无明文规定不为罪，法无明文规定不处罚。' },
    
    // ===== 文学 (4道) =====
    { id: 46, subject: '文学', grade: '大一', question: '分析《红楼梦》中林黛玉的人物形象。', answer: '林黛玉聪慧才情、多愁善感、孤高自许，是封建礼教下的悲剧典型。' },
    { id: 47, subject: '文学', grade: '大二', question: '中国现代文学中鲁迅的创作特点是什么？', answer: '鲁迅作品深刻批判社会，塑造了阿Q、祥林嫂等经典形象。' },
    { id: 48, subject: '文学', grade: '大一', question: '什么是现实主义文学？请举例说明。', answer: '现实主义真实反映社会生活。如《红楼梦》《人间喜剧》。' },
    { id: 49, subject: '文学', grade: '大二', question: '分析莎士比亚《哈姆雷特》中主人公的悲剧性格。', answer: '哈姆雷特性格犹豫不决，是"延宕的王子"，体现了人文主义者的困境。' },
];

// ===== 状态管理 =====
let allQuestions = [];
let currentSubject = 'all';
let currentPage = 0;
const PAGE_SIZE = 12;
let isLoading = false;
let hasMoreData = true;
let filteredQuestions = [...allQuestions];

// DOM 引用
const container = document.getElementById('questionsContainer');
const loadingIndicator = document.getElementById('loadingIndicator');
const noMore = document.getElementById('noMore');
const subjectTabs = document.querySelectorAll('.subject-tab');
const subjectName = document.getElementById('subjectName');
const questionCount = document.getElementById('questionCount');

// ===== 模态框 DOM 引用 =====
const modalOverlay = document.getElementById('modalOverlay');
const modalClose = document.getElementById('modalClose');
const modalTags = document.getElementById('modalTags');
const modalQuestion = document.getElementById('modalQuestion');
const modalAnswer = document.getElementById('modalAnswer');

// ===== 工具函数 =====
function escapeHtml(text) {
    return String(text)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

// ===== 收藏状态 =====
const bookmarks = new Set();

// ===== 获取学科显示名称 =====
function getSubjectDisplayName(subject) {
    const nameMap = {
        'all': '全部',
        '语文': '语文',
        '高数': '高数',
        '大物': '大物',
        '离散': '离散',
        '英语': '英语',
        'py': 'Python',
        '历史': '历史',
        '地理': '地理',
        '政治': '政治'
    };
    return nameMap[subject] || subject;
}

function getSubjectEmoji(subject) {
    const emojiMap = {
        'all': '📚',
        '语文': '📖',
        '高数': '📐',
        '大物': '⚡',
        '离散': '🔢',
        '英语': '🇬🇧',
        'py': '💻',
        '历史': '🏛️',
        '地理': '🌍',
        '政治': '🏛️'
    };
    return emojiMap[subject] || '📘';
}

// ===== 构建学科标签（根据实际数据动态生成） =====
function buildTabs() {
    const subjects = ['all', ...new Set(allQuestions.map(q => q.subject))];
    document.querySelectorAll('.subject-tab').forEach(tab => tab.remove());
    subjects.forEach(subject => {
        const btn = document.createElement('button');
        btn.className = 'subject-tab' + (subject === 'all' ? ' active' : '');
        btn.dataset.subject = subject;
        btn.textContent = getSubjectEmoji(subject) + ' ' + getSubjectDisplayName(subject);
        btn.addEventListener('click', function() {
            const sub = this.dataset.subject;
            if (sub !== currentSubject) {
                switchSubject(sub);
            }
        });
        document.querySelector('.subject-nav').appendChild(btn);
    });
}

// ===== 从后端加载错题数据 =====
function loadWrongQuestions() {
    fetch('/api/wrong_questions', {
        method: 'GET',
        credentials: 'same-origin'
    })
    .then(res => res.json())
    .then(data => {
        if (data.success && data.data) {
            allQuestions = data.data.map(r => ({
                id: r.id,
                subject: r.major,
                grade: r.sub || '',
                question: r.question,
                answer: r.answer || '',
                image_url: r.image_url || ''
            }));
        } else {
            allQuestions = [...FALLBACK_QUESTIONS];
        }
        buildTabs();
        switchSubject('all');
    })
    .catch(() => {
        allQuestions = [...FALLBACK_QUESTIONS];
        buildTabs();
        switchSubject('all');
    });
}

// ===== 渲染函数 =====
function renderQuestions(questions, append = false) {
    if (!append) {
        container.innerHTML = '';
    }
    
    if (questions.length === 0) {
        container.innerHTML = `
            <div class="empty-state">
                <div class="empty-icon">📚</div>
                <h3>暂无题目</h3>
                <p>当前分类下还没有题目</p>
            </div>
        `;
        return;
    }
    
    questions.forEach(item => {
        const isBookmarked = bookmarks.has(item.id);
        
        const card = document.createElement('div');
        card.className = 'question-card';
        card.dataset.id = item.id;
        card.innerHTML = `
            <div class="card-header">
                <div class="card-tags">
                    <span class="card-tag subject">${escapeHtml(getSubjectDisplayName(item.subject))}</span>
                    ${item.grade ? `<span class="card-tag grade">${escapeHtml(item.grade)}</span>` : ''}
                </div>
                <button class="card-bookmark ${isBookmarked ? 'active' : ''}" data-id="${item.id}">
                    ${isBookmarked ? '⭐' : '☆'}
                </button>
            </div>
            <div class="card-question">${escapeHtml(item.question).replace(/\n/g, '<br>')}</div>
            <div class="card-footer">
                <button class="card-btn" data-id="${item.id}">查看解答</button>
            </div>
        `;
        container.appendChild(card);
    });
}

// ===== 更新标题 =====
function updateTitle(subject) {
    const displayName = getSubjectDisplayName(subject);
    subjectName.textContent = displayName;
    const count = filteredQuestions.length;
    questionCount.textContent = `共 ${count} 道题目`;
}

// ===== 懒加载逻辑 =====
function loadMore() {
    if (isLoading || !hasMoreData) return;
    
    const start = currentPage * PAGE_SIZE;
    const end = start + PAGE_SIZE;
    const pageData = filteredQuestions.slice(start, end);
    
    if (pageData.length === 0) {
        hasMoreData = false;
        noMore.style.display = 'block';
        loadingIndicator.classList.remove('show');
        return;
    }
    
    isLoading = true;
    loadingIndicator.classList.add('show');
    
    setTimeout(() => {
        renderQuestions(pageData, true);
        currentPage++;
        isLoading = false;
        loadingIndicator.classList.remove('show');
        
        if (end >= filteredQuestions.length) {
            hasMoreData = false;
            noMore.style.display = 'block';
        }
    }, 300);
}

// ===== 切换学科 =====
function switchSubject(subject) {
    currentSubject = subject;
    currentPage = 0;
    hasMoreData = true;
    noMore.style.display = 'none';
    
    document.querySelectorAll('.subject-tab').forEach(tab => {
        tab.classList.toggle('active', tab.dataset.subject === subject);
    });
    
    if (subject === 'all') {
        filteredQuestions = [...allQuestions];
    } else {
        filteredQuestions = allQuestions.filter(q => q.subject === subject);
    }
    
    updateTitle(subject);
    container.innerHTML = '';
    
    if (filteredQuestions.length === 0) {
        container.innerHTML = `
            <div class="empty-state">
                <div class="empty-icon">📚</div>
                <h3>暂无题目</h3>
                <p>「${getSubjectDisplayName(subject)}」分类下还没有题目</p>
            </div>
        `;
        return;
    }
    
    loadMore();
}

// ============================================================
//  模态框功能（像作业帮一样的弹窗）
// ============================================================

function openModal(id) {
    const item = allQuestions.find(q => q.id === id);
    if (!item) return;
    
    // 设置标签
    modalTags.innerHTML = `
        <span class="tag subject">${escapeHtml(getSubjectDisplayName(item.subject))}</span>
        ${item.grade ? `<span class="tag grade">${escapeHtml(item.grade)}</span>` : ''}
    `;
    
    // 图片题目
    let imageHtml = '';
    if (item.image_url) {
        imageHtml = `<img src="${escapeHtml(item.image_url)}" alt="题目图片" style="max-width:100%;border-radius:10px;margin-bottom:12px;">`;
    }
    
    // 设置题目
    modalQuestion.innerHTML = imageHtml + escapeHtml(item.question).replace(/\n/g, '<br>');
    
    // 设置答案（支持换行）
    modalAnswer.textContent = item.answer;
    
    // 显示模态框
    modalOverlay.classList.add('open');
    document.body.style.overflow = 'hidden';
}

function closeModal() {
    modalOverlay.classList.remove('open');
    document.body.style.overflow = '';
}

// ===== 模态框事件监听 =====
modalClose.addEventListener('click', closeModal);

modalOverlay.addEventListener('click', function(e) {
    if (e.target === modalOverlay) {
        closeModal();
    }
});

document.addEventListener('keydown', function(e) {
    if (e.key === 'Escape') {
        closeModal();
    }
});

// ============================================================
//  卡片点击事件
// ============================================================

// 学科切换
subjectTabs.forEach(tab => {
    tab.addEventListener('click', function() {
        const subject = this.dataset.subject;
        if (subject !== currentSubject) {
            switchSubject(subject);
        }
    });
});

// 滚动懒加载
container.addEventListener('scroll', function() {
    if (this.scrollTop + this.clientHeight >= this.scrollHeight - 30) {
        loadMore();
    }
});

// 卡片点击（委托事件）
container.addEventListener('click', function(e) {
    // 收藏按钮
    const bookmarkBtn = e.target.closest('.card-bookmark');
    if (bookmarkBtn) {
        const id = parseInt(bookmarkBtn.dataset.id);
        toggleBookmark(id);
        e.stopPropagation();
        return;
    }
    
    // 查看解答按钮
    const answerBtn = e.target.closest('.card-btn');
    if (answerBtn) {
        const id = parseInt(answerBtn.dataset.id);
        openModal(id);
        e.stopPropagation();
        return;
    }
    
    // 点击卡片本身（除了按钮区域）
    const card = e.target.closest('.question-card');
    if (card && !e.target.closest('.card-btn') && !e.target.closest('.card-bookmark')) {
        const id = parseInt(card.dataset.id);
        openModal(id);
    }
});

// ===== 收藏功能 =====
function toggleBookmark(id) {
    if (bookmarks.has(id)) {
        bookmarks.delete(id);
    } else {
        bookmarks.add(id);
    }
    const cards = container.querySelectorAll('.question-card');
    cards.forEach(card => {
        const cardId = parseInt(card.dataset.id);
        if (cardId === id) {
            const btn = card.querySelector('.card-bookmark');
            const isBookmarked = bookmarks.has(id);
            btn.textContent = isBookmarked ? '⭐' : '☆';
            btn.classList.toggle('active', isBookmarked);
        }
    });
}

// ===== 初始化 =====
loadWrongQuestions();

console.log('📚 错题本已加载');
console.log(`📊 共 ${allQuestions.length} 道题目`);
console.log('📋 学科列表:', [...new Set(allQuestions.map(q => q.subject))]);
