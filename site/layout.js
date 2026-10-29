// The force layout of a large graph, worked out off the page's thread for the explorer (explorer.js draws such a graph
// on a canvas): a coarser repulsion than a small graph's, felt only nearby (300 px), no collision, and fewer steps,
// starting from positions that already group each source's records; the positions go back to the page as they settle,
// a few times a second. For 40,000 records this takes about 4 s where a small graph's forces would take 100 s.
importScripts("https://cdnjs.cloudflare.com/ajax/libs/d3/7.9.0/d3.min.js");

let run = 0;
onmessage = ({ data: m }) => {
  run = m.run;                                     // a newer run (or a stop) ends the one under way
  if (m.op !== "layout") return;
  const n = m.x.length, nodes = new Array(n);
  for (let i = 0; i < n; i++) nodes[i] = { x: m.x[i], y: m.y[i] };
  const links = new Array(m.links.length / 2);
  for (let e = 0; e < links.length; e++) links[e] = { source: m.links[2 * e], target: m.links[2 * e + 1] };
  const sim = d3.forceSimulation(nodes).stop().alpha(m.alpha).alphaDecay(n > 50000 ? 0.1 : 0.08)   // fewer steps for more records
    .force("link", d3.forceLink(links).distance(m.distance).strength(0.7))
    .force("charge", d3.forceManyBody().theta(2).distanceMax(300).strength((d, i) => m.charge - Math.min(m.degree[i], 60) * 8))
    .force("x", d3.forceX(m.cx).strength(0.03))
    .force("y", d3.forceY(m.cy).strength(0.03));
  const mine = m.run;
  const send = (done) => {
    const pos = new Float32Array(2 * n);
    for (let i = 0; i < n; i++) { pos[2 * i] = nodes[i].x; pos[2 * i + 1] = nodes[i].y; }
    postMessage({ run: mine, pos, done }, [pos.buffer]);
  };
  const step = () => {
    if (run !== mine) return;
    const t0 = performance.now();
    while (sim.alpha() >= sim.alphaMin() && performance.now() - t0 < 250) sim.tick();
    const done = sim.alpha() < sim.alphaMin();
    send(done);
    if (!done) setTimeout(step, 0);
  };
  step();
};
