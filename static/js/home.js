// 鼠标移入，显示登出按钮
document.querySelector('.info').addEventListener('mouseover', function() {
    document.querySelector('.show_hide').style.display = 'block';
});

// 鼠标移出，隐藏登出按钮
document.querySelector('.info').addEventListener('mouseout', function() {
    document.querySelector('.show_hide').style.display = 'none';
});

// 点击登出按钮后，发送登出命令
function logout() {
    window.location.href = '/logout';
}