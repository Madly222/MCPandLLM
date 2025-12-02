document.addEventListener('DOMContentLoaded', () => {
    const input = document.getElementById('prompt');
    const sendBtn = document.getElementById('sendBtn');
    const chatContainer = document.getElementById('chat-container');
    const uploadBtn = document.getElementById('uploadBtn');
    const fileInput = document.getElementById('fileInput');

    if (!input || !sendBtn || !chatContainer) {
        console.log('Элементы чата не найдены (возможно страница логина)');
        return;
    }

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
                headers: {
                    'Content-Type': 'application/json'
                },
                credentials: 'include',
                body: JSON.stringify({ prompt: message })
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
        if (role === 'Вы') msgDiv.className = 'message user-msg';
        else if (role === 'Помощник') msgDiv.className = 'message assistant-msg';
        else msgDiv.className = 'message';

        msgDiv.innerText = `${role}:\n${text}`;
        chatContainer.appendChild(msgDiv);
        chatContainer.scrollTop = chatContainer.scrollHeight;
    }

    if (uploadBtn && fileInput) {
        uploadBtn.addEventListener('click', () => {
            fileInput.click();
        });

        fileInput.addEventListener('change', async () => {
            const file = fileInput.files[0];
            if (!file) return;

            const formData = new FormData();
            formData.append('file', file);

            try {
                const res = await fetch('/upload', {
                    method: 'POST',
                    credentials: 'include',
                    body: formData
                });

                const data = await res.json();
                alert(data.message || 'Файл загружен');
            } catch (err) {
                alert('Ошибка при загрузке файла');
                console.error(err);
            }

            fileInput.value = '';
        });
    }

    // Tooltip первого уровня (над кнопкой ?)
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
            }, 300);
        });

        tooltipText.addEventListener('mouseenter', () => {
            if (hideTimeout) clearTimeout(hideTimeout);
        });

        tooltipText.addEventListener('mouseleave', () => {
            hideTimeout = setTimeout(() => {
                tooltipText.style.visibility = 'hidden';
                tooltipText.style.opacity = '0';
            }, 200);
        });
    }

    // Inner tooltip (второй уровень) - слева от первого блока
    const innerTooltips = document.querySelectorAll('.inner-tooltip');
    innerTooltips.forEach(inner => {
        const innerText = inner.querySelector('.inner-tooltiptext');
        if (!innerText) return;

        inner.addEventListener('mouseenter', () => {
            // Сначала сбрасываем позицию на дефолтную (слева)
            innerText.style.right = '100%';
            innerText.style.left = 'auto';
            innerText.style.top = '50%';
            innerText.style.bottom = 'auto';
            innerText.style.transform = 'translateY(-50%)';
            innerText.style.marginRight = '10px';
            innerText.style.marginLeft = '0';

            // Показываем
            innerText.style.visibility = 'visible';
            innerText.style.opacity = '1';

            // Проверяем границы экрана после отрисовки
            requestAnimationFrame(() => {
                const rect = innerText.getBoundingClientRect();
                const viewportHeight = window.innerHeight;

                // Если выходит слева за экран - показываем справа
                if (rect.left < 5) {
                    innerText.style.right = 'auto';
                    innerText.style.left = '100%';
                    innerText.style.marginRight = '0';
                    innerText.style.marginLeft = '10px';
                }

                // Пересчитываем после возможного сдвига
                const newRect = innerText.getBoundingClientRect();

                // Если выходит сверху
                if (newRect.top < 5) {
                    innerText.style.top = '0';
                    innerText.style.transform = 'none';
                }

                // Если выходит снизу
                if (newRect.bottom > viewportHeight - 5) {
                    innerText.style.top = 'auto';
                    innerText.style.bottom = '0';
                    innerText.style.transform = 'none';
                }
            });
        });

        inner.addEventListener('mouseleave', () => {
            innerText.style.visibility = 'hidden';
            innerText.style.opacity = '0';
        });
    });
});