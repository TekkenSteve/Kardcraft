// 调试认证状态的脚本
// 在浏览器控制台运行

console.log("=== 认证状态调试 ===");

// 1. 检查 cookies
console.log("当前 cookies:", document.cookie);

// 2. 检查 Kratos session
const cookies = document.cookie.split(';');
let sessionToken = null;
for (const cookie of cookies) {
    const [name, value] = cookie.trim().split('=');
    if (name === 'ory_kratos_session') {
        sessionToken = decodeURIComponent(value);
        console.log("找到 session token:", sessionToken.substring(0, 20) + "...");
    }
}

if (!sessionToken) {
    console.error("❌ 没有找到 ory_kratos_session cookie");
} else {
    console.log("✅ 找到 session token");
}

// 3. 测试 API 调用
fetch('/auth/sessions/whoami', {
    credentials: 'include'
})
.then(response => {
    if (response.ok) {
        return response.json();
    } else {
        throw new Error(`HTTP ${response.status}: ${response.statusText}`);
    }
})
.then(session => {
    console.log("✅ 当前会话信息:", session);
})
.catch(error => {
    console.error("❌ 会话验证失败:", error.message);
});

// 4. 测试 API 代理
fetch('/api/v1/tasks', {
    credentials: 'include'
})
.then(response => {
    console.log("API 测试响应状态:", response.status);
    return response.text();
})
.then(text => {
    console.log("API 测试响应内容:", text);
})
.catch(error => {
    console.error("❌ API 测试失败:", error);
});