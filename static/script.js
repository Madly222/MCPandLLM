const input = document.getElementById('prompt');
const sendBtn = document.getElementById('sendBtn');
const chat = document.getElementById('chat');

sendBtn.addEventListener('click', sendPrompt);
input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') sendPrompt();
});

async function sendPrompt() {
    const message = input.value.trim();
    if (!message) return;
    appendChat('Вы', message);
    input.value = '';

    try {
        const res = await fetch('/query', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ prompt: message, user_id: 'default' })
        });
        const data = await res.json();
        appendChat('Помощник', data.response || 'Ошибка при получении ответа');
    } catch (err) {
        appendChat('Система', 'Ошибка при соединении с сервером');
        console.error(err);
    }
}

function appendChat(role, text) {
    chat.innerHTML += `<b>${role}:</b> ${text}<br>`;
    chat.scrollTop = chat.scrollHeight;
}
