let count = 0;
const display = document.getElementById("count");
const render = () => {
  display.textContent = count;
  display.style.color = count > 0 ? "green" : count < 0 ? "crimson" : "inherit";
};
document.getElementById("inc").onclick = () => { count++; render(); };
document.getElementById("dec").onclick = () => { count--; render(); };
document.getElementById("reset").onclick = () => { count = 0; render(); };
