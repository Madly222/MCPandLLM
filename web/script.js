document.addEventListener('DOMContentLoaded', () => {
    const input = document.getElementById('prompt');
    const sendBtn = document.getElementById('sendBtn');
    const chatContainer = document.getElementById('chat-container');

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
        const msgDiv = document.createElement('div');

        if (role === 'Вы') {
            msgDiv.className = 'message user-msg';
        } else if (role === 'Помощник') {
            msgDiv.className = 'message assistant-msg';
        } else {
            msgDiv.className = 'message';
        }

        msgDiv.innerHTML = `<b>${role}:</b> ${text}`;
        chatContainer.appendChild(msgDiv);
        chatContainer.scrollTop = chatContainer.scrollHeight;
    }

    // Первый уровень тултипа с задержкой 500мс
    const tooltip = document.querySelector('.tooltip');
    if (tooltip) {
        const tooltipText = tooltip.querySelector('.tooltiptext');
        let hideTimeout;

        tooltip.addEventListener('mouseenter', () => {
            if (hideTimeout) clearTimeout(hideTimeout);
            tooltipText.style.visibility = 'visible';
            tooltipText.style.opacity = '1';
        });

        tooltip.addEventListener('mouseleave', () => {
            hideTimeout = setTimeout(() => {
                tooltipText.style.visibility = 'hidden';
                tooltipText.style.opacity = '0';
            }, 500);
        });

        tooltipText.addEventListener('mouseenter', () => {
            if (hideTimeout) clearTimeout(hideTimeout);
        });

        tooltipText.addEventListener('mouseleave', () => {
            hideTimeout = setTimeout(() => {
                tooltipText.style.visibility = 'hidden';
                tooltipText.style.opacity = '0';
            }, 250);
        });
    }

    // Второй уровень тултипа без задержки и с проверкой экрана
    const innerTooltips = document.querySelectorAll('.inner-tooltip');
    innerTooltips.forEach(inner => {
        const innerText = inner.querySelector('.inner-tooltiptext');
        if (!innerText) return;

        inner.addEventListener('mouseenter', () => {
            // Сначала показать временно для расчета
            innerText.style.visibility = 'hidden';
            innerText.style.display = 'block';

            const rect = innerText.getBoundingClientRect();
            const viewportHeight = window.innerHeight || document.documentElement.clientHeight;

            // Расположение тултипа
            if (rect.bottom > viewportHeight) {
                innerText.style.bottom = 'auto';
                innerText.style.top = '100%';
            } else {
                innerText.style.bottom = '100%';
                innerText.style.top = 'auto';
            }

            innerText.style.display = ''; // вернуть исходное состояние
            innerText.style.visibility = 'visible';
            innerText.style.opacity = '1';
        });

        inner.addEventListener('mouseleave', () => {
            innerText.style.visibility = 'hidden';
            innerText.style.opacity = '0';
            innerText.style.top = '';
            innerText.style.bottom = '100%';
        });
    });
});