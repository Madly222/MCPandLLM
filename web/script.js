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

        msgDiv.innerText = `${role}:\n${text}`;
        chatContainer.appendChild(msgDiv);
        chatContainer.scrollTop = chatContainer.scrollHeight;
    }

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

    const innerTooltips = document.querySelectorAll('.inner-tooltip');
    innerTooltips.forEach(inner => {
        const innerText = inner.querySelector('.inner-tooltiptext');
        if (!innerText) return;

        inner.addEventListener('mouseenter', () => {
            innerText.style.visibility = 'hidden';
            innerText.style.display = 'block';
            innerText.style.opacity = '0';

            const rectParent = inner.getBoundingClientRect();
            const tooltipHeight = innerText.offsetHeight;
            const viewportHeight = window.innerHeight || document.documentElement.clientHeight;

            if (rectParent.bottom + tooltipHeight > viewportHeight) {
                innerText.style.top = `${-tooltipHeight}px`; // показываем выше родителя
            } else {
                innerText.style.top = `${inner.offsetHeight}px`; // показываем ниже родителя
            }

            innerText.style.visibility = 'visible';
            innerText.style.opacity = '1';
            innerText.style.display = '';
        });

        inner.addEventListener('mouseleave', () => {
            innerText.style.visibility = 'hidden';
            innerText.style.opacity = '0';
            innerText.style.top = '';
        });
    });
});