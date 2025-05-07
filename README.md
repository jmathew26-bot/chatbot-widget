# chatbot-widget
// widget.js
(function () {
  const bubble = document.createElement("div");
  bubble.innerText = "💬";
  bubble.style.position = "fixed";
  bubble.style.bottom = "20px";
  bubble.style.right = "20px";
  bubble.style.width = "60px";
  bubble.style.height = "60px";
  bubble.style.background = "#007bff";
  bubble.style.color = "#fff";
  bubble.style.borderRadius = "50%";
  bubble.style.display = "flex";
  bubble.style.alignItems = "center";
  bubble.style.justifyContent = "center";
  bubble.style.cursor = "pointer";
  bubble.style.zIndex = "9999";

  const iframe = document.createElement("iframe");
  iframe.src = "https://your-chatbot-ui-page.com/chat.html"; // update later
  iframe.style.display = "none";
  iframe.style.position = "fixed";
  iframe.style.bottom = "90px";
  iframe.style.right = "20px";
  iframe.style.width = "350px";
  iframe.style.height = "500px";
  iframe.style.border = "1px solid #ccc";
  iframe.style.zIndex = "9999";
  iframe.style.borderRadius = "10px";

  bubble.addEventListener("click", () => {
    iframe.style.display = iframe.style.display === "none" ? "block" : "none";
  });

  document.body.appendChild(bubble);
  document.body.appendChild(iframe);
})();

<!-- chat.html -->
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>Chatbot</title>
</head>
<body>
  <h2>Chatbot Coming Soon!</h2>
  <p>This is where your GPT chat UI will go.</p>
</body>
</html>


  document.body.appendChild(bubble);
  document.body.appendChild(iframe);
})();
