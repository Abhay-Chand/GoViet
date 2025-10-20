const sendBtn = document.getElementById('send-btn');
const userInput = document.getElementById('user-input');
const chatBox = document.getElementById('chat-box');

async function sendQuery() {
  const query = userInput.value.trim();
  if (!query) return;

  // Add user bubble
  const userBubble = document.createElement('div');
  userBubble.className = 'bg-blue-100 text-blue-800 p-3 rounded-xl w-fit ml-auto';
  userBubble.textContent = query;
  chatBox.appendChild(userBubble);

  userInput.value = '';

  // Add loading bubble
  const loadingBubble = document.createElement('div');
  loadingBubble.className = 'bg-gray-100 text-gray-500 p-3 rounded-xl w-fit';
  loadingBubble.textContent = '⏳ Thinking...';
  chatBox.appendChild(loadingBubble);
  chatBox.scrollTop = chatBox.scrollHeight;

  try {
    const response = await fetch('/ask', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ query })
    });
    const data = await response.json();
    loadingBubble.remove();

   const botBubble = document.createElement('div');
   botBubble.className = 'bg-green-50 text-gray-800 p-4 rounded-xl prose prose-sm max-w-none';
   botBubble.innerHTML = marked.parse(data.answer || data.error || "❌ Something went wrong");
   chatBox.appendChild(botBubble);

  } catch (err) {
    loadingBubble.textContent = '❌ Error connecting to server';
  }
}

sendBtn.addEventListener('click', sendQuery);
userInput.addEventListener('keypress', e => {
  if (e.key === 'Enter') sendQuery();
});
