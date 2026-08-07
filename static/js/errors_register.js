
// ============================================================
//  subjects.js - 大学学科题库浏览 + 懒加载
//  确保点击学科标签能正确筛选题目
// ============================================================

// ===== 模拟题库数据（大学学科）- 每个学科至少 4 道题 =====
const allQuestions = [
    // ===== 高等数学 (6道) =====
    { id: 1, subject: '高等数学', grade: '大一', difficulty: '中等', question: '求极限 lim(x→0) (sin x)/x', views: 342, likes: 28, comments: 12 },
    { id: 2, subject: '高等数学', grade: '大一', difficulty: '简单', question: '求导数：y = x³ + 2x² - 5x + 1', views: 156, likes: 14, comments: 3 },
    { id: 3, subject: '高等数学', grade: '大二', difficulty: '困难', question: '计算定积分 ∫₀¹ x² dx', views: 287, likes: 22, comments: 8 },
    { id: 4, subject: '高等数学', grade: '大一', difficulty: '中等', question: '判断级数 ∑(1/n²) 的收敛性', views: 234, likes: 18, comments: 6 },
    { id: 5, subject: '高等数学', grade: '大二', difficulty: '困难', question: '求微分方程 dy/dx = 2x 的通解', views: 198, likes: 15, comments: 5 },
    { id: 6, subject: '高等数学', grade: '大一', difficulty: '简单', question: '求函数 f(x) = x² 在 x=1 处的切线方程', views: 112, likes: 8, comments: 2 },
    
    // ===== 线性代数 (5道) =====
    { id: 7, subject: '线性代数', grade: '大一', difficulty: '中等', question: '计算矩阵 A = [[1,2],[3,4]] 的行列式', views: 267, likes: 20, comments: 7 },
    { id: 8, subject: '线性代数', grade: '大二', difficulty: '困难', question: '求矩阵 A = [[1,2,3],[4,5,6],[7,8,9]] 的秩', views: 189, likes: 12, comments: 4 },
    { id: 9, subject: '线性代数', grade: '大一', difficulty: '简单', question: '判断向量组 α₁=(1,0), α₂=(0,1) 是否线性相关', views: 134, likes: 9, comments: 3 },
    { id: 10, subject: '线性代数', grade: '大二', difficulty: '中等', question: '求解线性方程组：x + y = 3, 2x - y = 0', views: 156, likes: 11, comments: 3 },
    { id: 11, subject: '线性代数', grade: '大一', difficulty: '中等', question: '计算矩阵乘法：[[1,2],[3,4]] × [[5,6],[7,8]]', views: 145, likes: 10, comments: 4 },
    
    // ===== 概率论 (5道) =====
    { id: 12, subject: '概率论', grade: '大二', difficulty: '中等', question: '同时掷两枚骰子，求点数和为 7 的概率', views: 312, likes: 25, comments: 9 },
    { id: 13, subject: '概率论', grade: '大二', difficulty: '困难', question: '设随机变量 X ~ N(0,1)，求 P(X > 1.96)', views: 223, likes: 16, comments: 5 },
    { id: 14, subject: '概率论', grade: '大一', difficulty: '简单', question: '抛一枚硬币三次，求恰好出现两次正面的概率', views: 98, likes: 6, comments: 2 },
    { id: 15, subject: '概率论', grade: '大二', difficulty: '中等', question: '某产品合格率为 0.9，随机抽取 10 件，求恰有 8 件合格的概率', views: 178, likes: 13, comments: 4 },
    { id: 100, subject: '概率论', grade: '大三', difficulty: '困难', question: '设 X 服从泊松分布 P(λ)，求 E(X) 和 D(X)', views: 210, likes: 17, comments: 6 },
    
    // ===== 大学物理 (5道) =====
    { id: 16, subject: '大学物理', grade: '大二', difficulty: '困难', question: '一质点做简谐运动，振幅为 A，周期为 T，求其最大速度', views: 289, likes: 21, comments: 7 },
    { id: 17, subject: '大学物理', grade: '大一', difficulty: '中等', question: '一物体从静止开始自由下落 5s，求下落高度', views: 167, likes: 12, comments: 4 },
    { id: 18, subject: '大学物理', grade: '大二', difficulty: '中等', question: '两个点电荷相距 r，求它们之间的库仑力', views: 145, likes: 10, comments: 3 },
    { id: 19, subject: '大学物理', grade: '大一', difficulty: '简单', question: '匀速圆周运动的向心加速度公式是什么？', views: 89, likes: 5, comments: 1 },
    { id: 20, subject: '大学物理', grade: '大二', difficulty: '困难', question: '推导理想气体的状态方程 PV = nRT', views: 234, likes: 18, comments: 6 },
    
    // ===== 化学 (4道) =====
    { id: 21, subject: '化学', grade: '大一', difficulty: '中等', question: '写出化学反应方程式：Fe + CuSO₄ → ?', views: 156, likes: 11, comments: 3 },
    { id: 22, subject: '化学', grade: '大二', difficulty: '困难', question: '计算 pH = 3 的盐酸溶液中 H⁺ 的浓度', views: 198, likes: 14, comments: 5 },
    { id: 23, subject: '化学', grade: '大一', difficulty: '简单', question: '水的化学式是什么？', views: 67, likes: 3, comments: 0 },
    { id: 24, subject: '化学', grade: '大二', difficulty: '中等', question: '什么是氧化还原反应？请举例说明。', views: 123, likes: 8, comments: 2 },
    
    // ===== 生物学 (4道) =====
    { id: 25, subject: '生物学', grade: '大二', difficulty: '中等', question: 'DNA 的复制方式是什么？', views: 189, likes: 15, comments: 5 },
    { id: 26, subject: '生物学', grade: '大一', difficulty: '简单', question: '细胞膜的主要成分是什么？', views: 78, likes: 4, comments: 1 },
    { id: 27, subject: '生物学', grade: '大二', difficulty: '困难', question: '简述光合作用的光反应与暗反应的关系。', views: 256, likes: 20, comments: 8 },
    { id: 28, subject: '生物学', grade: '大一', difficulty: '中等', question: '什么是基因？基因在染色体上的位置叫什么？', views: 134, likes: 9, comments: 3 },
    
    // ===== 计算机科学 (5道) =====
    { id: 29, subject: '计算机科学', grade: '大一', difficulty: '中等', question: '什么是时间复杂度？请分析冒泡排序的时间复杂度。', views: 345, likes: 30, comments: 12 },
    { id: 30, subject: '计算机科学', grade: '大二', difficulty: '困难', question: '写出二叉树的三种遍历方式及其代码实现。', views: 289, likes: 24, comments: 9 },
    { id: 31, subject: '计算机科学', grade: '大一', difficulty: '简单', question: '什么是变量？在 Python 中如何定义变量？', views: 98, likes: 6, comments: 2 },
    { id: 32, subject: '计算机科学', grade: '大二', difficulty: '中等', question: '解释什么是递归，并给出一个简单的递归例子。', views: 178, likes: 14, comments: 5 },
    { id: 33, subject: '计算机科学', grade: '大三', difficulty: '困难', question: '什么是死锁？产生死锁的四个必要条件是什么？', views: 267, likes: 22, comments: 8 },
    
    // ===== 经济学 (4道) =====
    { id: 34, subject: '经济学', grade: '大一', difficulty: '简单', question: '什么是需求定律？请用日常生活中的例子说明。', views: 123, likes: 8, comments: 3 },
    { id: 35, subject: '经济学', grade: '大二', difficulty: '中等', question: '解释 GDP 的含义，并说明其计算方法。', views: 198, likes: 16, comments: 6 },
    { id: 36, subject: '经济学', grade: '大二', difficulty: '困难', question: '分析通货膨胀的成因及其对经济的影响。', views: 234, likes: 19, comments: 7 },
    { id: 37, subject: '经济学', grade: '大一', difficulty: '中等', question: '什么是边际效用递减规律？', views: 145, likes: 10, comments: 3 },
    
    // ===== 管理学 (4道) =====
    { id: 38, subject: '管理学', grade: '大一', difficulty: '简单', question: '管理的四大基本职能是什么？', views: 112, likes: 7, comments: 2 },
    { id: 39, subject: '管理学', grade: '大二', difficulty: '中等', question: '马斯洛需求层次理论包含哪些内容？', views: 189, likes: 15, comments: 5 },
    { id: 40, subject: '管理学', grade: '大三', difficulty: '困难', question: '什么是 SWOT 分析？如何在实际管理中使用？', views: 256, likes: 21, comments: 8 },
    { id: 41, subject: '管理学', grade: '大二', difficulty: '中等', question: '简述泰勒的科学管理理论的核心思想。', views: 134, likes: 9, comments: 3 },
    
    // ===== 法学 (4道) =====
    { id: 42, subject: '法学', grade: '大一', difficulty: '中等', question: '法的基本特征是什么？', views: 167, likes: 12, comments: 4 },
    { id: 43, subject: '法学', grade: '大二', difficulty: '困难', question: '分析我国宪法的基本原则。', views: 234, likes: 18, comments: 6 },
    { id: 44, subject: '法学', grade: '大一', difficulty: '简单', question: '什么是法律关系？构成要素有哪些？', views: 89, likes: 5, comments: 1 },
    { id: 45, subject: '法学', grade: '大二', difficulty: '中等', question: '简述罪刑法定原则的含义。', views: 145, likes: 10, comments: 3 },
    
    // ===== 文学 (4道) =====
    { id: 46, subject: '文学', grade: '大一', difficulty: '中等', question: '分析《红楼梦》中林黛玉的人物形象。', views: 389, likes: 35, comments: 14 },
    { id: 47, subject: '文学', grade: '大二', difficulty: '困难', question: '中国现代文学中鲁迅的创作特点是什么？', views: 278, likes: 23, comments: 9 },
    { id: 48, subject: '文学', grade: '大一', difficulty: '简单', question: '什么是现实主义文学？请举例说明。', views: 98, likes: 6, comments: 2 },
    { id: 49, subject: '文学', grade: '大二', difficulty: '中等', question: '分析莎士比亚《哈姆雷特》中主人公的悲剧性格。', views: 312, likes: 28, comments: 11 },
];

// ===== 状态管理 =====
let currentSubject = 'all';
let currentPage = 0;
const PAGE_SIZE = 12;  // 每次加载 12 条
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

// ===== 收藏状态 =====
const bookmarks = new Set();

// ===== 获取学科显示名称 =====
function getSubjectDisplayName(subject) {
    const nameMap = {
        'all': '全部',
        '高等数学': '高等数学',
        '线性代数': '线性代数',
        '概率论': '概率论',
        '大学物理': '大学物理',
        '化学': '化学',
        '生物学': '生物学',
        '计算机科学': '计算机科学',
        '经济学': '经济学',
        '管理学': '管理学',
        '法学': '法学',
        '文学': '文学'
    };
    return nameMap[subject] || subject;
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
        const difficultyClass = item.difficulty === '困难' ? 'difficulty-hard' :
                               item.difficulty === '中等' ? 'difficulty-medium' : 'difficulty-easy';
        
        const card = document.createElement('div');
        card.className = 'question-card';
        card.dataset.id = item.id;
        card.innerHTML = `
            <div class="card-header">
                <div class="card-tags">
                    <span class="card-tag subject">${item.subject}</span>
                    <span class="card-tag grade">${item.grade}</span>
                    <span class="card-tag ${difficultyClass}">${item.difficulty}</span>
                </div>
                <button class="card-bookmark ${isBookmarked ? 'active' : ''}" data-id="${item.id}">
                    ${isBookmarked ? '⭐' : '☆'}
                </button>
            </div>
            <div class="card-question">${item.question}</div>
            <div class="card-footer">
                <div class="card-stats">
                    <span>👁️ ${item.views}</span>
                    <span>❤️ ${item.likes}</span>
                    <span>💬 ${item.comments}</span>
                </div>
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
    
    // 更新 tab 样式
    subjectTabs.forEach(tab => {
        tab.classList.toggle('active', tab.dataset.subject === subject);
    });
    
    // 筛选数据 - 关键：根据 subject 精确匹配
    if (subject === 'all') {
        filteredQuestions = [...allQuestions];
    } else {
        filteredQuestions = allQuestions.filter(q => q.subject === subject);
    }
    
    // 更新标题
    updateTitle(subject);
    
    // 重置容器并加载第一页
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

// ===== 事件监听 =====

// 学科切换 - 点击标签筛选对应学科
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

// 卡片点击
container.addEventListener('click', function(e) {
    const card = e.target.closest('.question-card');
    const bookmarkBtn = e.target.closest('.card-bookmark');
    const answerBtn = e.target.closest('.card-btn');
    
    if (bookmarkBtn) {
        const id = parseInt(bookmarkBtn.dataset.id);
        toggleBookmark(id);
        e.stopPropagation();
        return;
    }
    
    if (answerBtn) {
        const id = parseInt(answerBtn.dataset.id);
        showAnswer(id);
        e.stopPropagation();
        return;
    }
    
    if (card) {
        const id = parseInt(card.dataset.id);
        showAnswer(id);
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

// ===== 查看解答 =====
function showAnswer(id) {
    const question = allQuestions.find(q => q.id === id);
    if (!question) return;
    alert(`📚 ${question.subject} · ${question.grade}\n\n题目：${question.question}\n\n解答：\n${getAnswerById(id)}`);
}

// ===== 模拟答案数据 =====
function getAnswerById(id) {
    const answers = {
        1: 'lim(x→0) (sin x)/x = 1。这是重要极限。',
        2: "y' = 3x² + 4x - 5。使用幂函数求导法则。",
        3: '∫₀¹ x² dx = [x³/3]₀¹ = 1/3。',
        4: '∑(1/n²) 收敛。这是 p-级数，p=2>1。',
        5: 'y = x² + C。分离变量法求解。',
        6: 'y = 2x - 1。切线斜率 k = f\'(1) = 2，过点 (1,1)。',
        7: 'det(A) = 1×4 - 2×3 = 4-6 = -2。',
        8: 'r(A) = 2。因为三阶矩阵的行列式为 0，但存在二阶非零子式。',
        9: '线性无关。因为不存在非零常数 k₁, k₂ 使 k₁α₁ + k₂α₂ = 0。',
        10: 'x = 1, y = 2。用消元法求解。',
        11: '[[19,22],[43,50]]。按矩阵乘法规则计算。',
        12: 'P = 6/36 = 1/6。共有 6 种组合(1,6),(2,5),(3,4),(4,3),(5,2),(6,1)。',
        13: 'P(X > 1.96) = 0.025。标准正态分布的上尾概率。',
        14: 'P = C(3,2)×(1/2)³ = 3/8。',
        15: 'P = C(10,8)×0.9⁸×0.1² ≈ 0.1937。二项分布。',
        16: 'v_max = 2πA/T。简谐运动的最大速度在平衡位置。',
        17: 'h = (1/2)gt² = (1/2)×10×25 = 125m。',
        18: 'F = kq₁q₂/r²。库仑定律。',
        19: 'a = v²/r = ω²r。向心加速度公式。',
        20: '由玻意耳定律、查理定律、盖-吕萨克定律推导。PV = nRT。',
        21: 'Fe + CuSO₄ = FeSO₄ + Cu。置换反应。',
        22: '[H⁺] = 10⁻³ mol/L。pH = -lg[H⁺]。',
        23: 'H₂O。水分子由一个氧原子和两个氢原子组成。',
        24: '氧化还原反应是电子转移的反应。例：2Mg + O₂ = 2MgO。',
        25: '半保留复制。DNA 双链分开，各以一条链为模板合成新链。',
        26: '磷脂双分子层和蛋白质。细胞膜的基本骨架是磷脂双分子层。',
        27: '光反应为暗反应提供 ATP 和 [H]，暗反应为光反应提供 ADP 和 Pi。',
        28: '基因是遗传的基本单位。位置在染色体上叫基因座。',
        29: '时间复杂度描述算法运行时间与输入规模的关系。冒泡排序 O(n²)。',
        30: '前序：根-左-右；中序：左-根-右；后序：左-右-根。',
        31: '变量是存储数据的容器。Python: x = 5。',
        32: '递归是函数调用自身。例：求 n! = n×(n-1)!',
        33: '死锁是多个进程相互等待资源。必要条件：互斥、占有等待、不可剥夺、循环等待。',
        34: '需求定律：价格上升，需求量下降。例：商场打折销量增加。',
        35: 'GDP 是国内生产总值，核算一定时期内生产的最终产品价值。',
        36: '通胀由货币过多或成本上升引起，会导致购买力下降。',
        37: '边际效用递减：随着消费量增加，每单位商品带来的效用递减。',
        38: '计划、组织、领导、控制。',
        39: '生理需求、安全需求、社交需求、尊重需求、自我实现。',
        40: 'SWOT 分析优势、劣势、机会、威胁。用于战略决策。',
        41: '泰勒科学管理强调标准化、分工和效率。',
        42: '法的基本特征：规范性、国家强制性、普遍性、程序性。',
        43: '我国宪法原则：人民主权、法治、人权保障、权力制约。',
        44: '法律关系是法律规范调整社会关系形成的权利义务关系。',
        45: '罪刑法定：法无明文规定不为罪，法无明文规定不处罚。',
        46: '林黛玉聪慧才情、多愁善感、孤高自许，是封建礼教下的悲剧典型。',
        47: '鲁迅作品深刻批判社会，塑造了阿Q、祥林嫂等经典形象。',
        48: '现实主义真实反映社会生活。如《红楼梦》《人间喜剧》。',
        49: '哈姆雷特性格犹豫不决，是"延宕的王子"，体现了人文主义者的困境。',
        100: 'E(X) = λ，D(X) = λ。泊松分布的期望和方差都等于参数 λ。'
    };
    return answers[id] || '暂无详细解答。';
}

// ===== 初始化 =====
switchSubject('all');

// ===== 控制台输出调试信息 =====
console.log('📚 学科题库已加载');
console.log(`📊 共 ${allQuestions.length} 道题目`);
console.log('📋 学科列表:', [...new Set(allQuestions.map(q => q.subject))]);
console.log('💡 点击学科标签可筛选对应题目');