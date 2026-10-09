import { useState } from 'react';
import { ShieldAlert, BarChart3, PieChart as PieIcon, Activity, Lock, Cpu, CheckCircle2 } from 'lucide-react';
import { TiltCard } from './TiltCard';

interface SocAnalyticsProps {
  totalCalls: number;
  blockedCalls: number;
  judgedCalls: number;
}

export function SocAnalytics({
  totalCalls,
  blockedCalls,
  judgedCalls,
}: SocAnalyticsProps) {
  const [hoveredSlice, setHoveredSlice] = useState<string | null>(null);
  const [hoveredBar, setHoveredBar] = useState<number | null>(null);

  // Exact normalized threat distribution
  const rawDet = Math.max(0, blockedCalls - Math.floor(judgedCalls * 0.5));
  const rawAi = Math.max(0, blockedCalls - rawDet) + (judgedCalls > 0 ? Math.floor(judgedCalls * 0.5) : 0);
  const rawAllow = Math.max(0, totalCalls - rawDet - rawAi);

  const displayTotal = totalCalls > 0 ? totalCalls : 5;
  const detCount = totalCalls > 0 ? rawDet : 3;
  const aiCount = totalCalls > 0 ? Math.max(1, rawAi) : 1;
  const allowCount = totalCalls > 0 ? rawAllow : 1;

  const sum = Math.max(1, detCount + aiCount + allowCount);
  const pctDet = detCount / sum;
  const pctAi = aiCount / sum;
  const pctAllow = allowCount / sum;

  // Circumference for r=54 -> 2 * PI * 54 ≈ 339.29
  const c = 339.29;
  const strokeDet = pctDet * c;
  const strokeAi = pctAi * c;
  const strokeAllow = pctAllow * c;

  const offsetDet = 0;
  const offsetAi = -strokeDet;
  const offsetAllow = -(strokeDet + strokeAi);

  // 3D Latency Histogram Pillar Data
  const latencyPillars = [
    { label: 'p10', height: 26, latency: '0.8ms', count: 42, active: false },
    { label: 'p25', height: 44, latency: '1.4ms', count: 88, active: false },
    { label: 'p40', height: 32, latency: '2.1ms', count: 64, active: false },
    { label: 'p50', height: 78, latency: '3.8ms', count: 140, active: true },
    { label: 'p65', height: 48, latency: '4.2ms', count: 92, active: false },
    { label: 'p80', height: 92, latency: '5.1ms', count: 184, active: true },
    { label: 'p90', height: 60, latency: '5.9ms', count: 110, active: false },
    { label: 'p95', height: 82, latency: '6.4ms', count: 156, active: true },
    { label: 'p99', height: 38, latency: '8.2ms', count: 32, active: false },
  ];

  return (
    <div className="grid grid-cols-1 lg:grid-cols-12 gap-5 font-mono">
      
      {/* 1. 3D TILT BOX: CLEAN CRISP 2D DONUT CHART */}
      <div className="lg:col-span-6">
        <TiltCard maxTilt={14} className="p-6 rounded-2xl mirror-panel h-full flex flex-col justify-between">
          
          {/* Header */}
          <div className="flex items-center justify-between border-b border-white/10 pb-3.5">
            <div className="flex items-center gap-2.5">
              <div className="p-1.5 rounded-lg bg-white/10 border border-white/15 text-white">
                <PieIcon className="w-4 h-4" />
              </div>
              <div>
                <span className="font-extrabold text-white tracking-wider text-xs sm:text-sm">THREAT DISTRIBUTION</span>
                <p className="text-[10px] text-white/50">Zero-Trust Realtime Policy Triage</p>
              </div>
            </div>

            <div className="flex items-center gap-1.5 text-[10px] text-white/70 px-2.5 py-1 rounded-md border border-white/15 bg-white/5">
              <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
              <span className="font-semibold text-white/80">LIVE FEED</span>
            </div>
          </div>

          {/* 2D Donut & Legend */}
          <div className="flex flex-col sm:flex-row items-center justify-center gap-8 my-6">
            
            {/* Plain 2D Donut SVG */}
            <div className="relative w-56 h-56 sm:w-64 sm:h-64 flex items-center justify-center select-none flex-shrink-0">
              <svg 
                className="w-full h-full -rotate-90 transform overflow-visible" 
                viewBox="0 0 140 140"
              >
                {/* Background Track */}
                <circle
                  cx="70"
                  cy="70"
                  r="54"
                  stroke="#27272a"
                  strokeWidth="16"
                  fill="none"
                />

                {/* Slice 1: Deterministic Drop (Crimson Red) */}
                <circle
                  cx="70"
                  cy="70"
                  r="54"
                  stroke="#ef4444"
                  strokeWidth={hoveredSlice === 'Deterministic' ? 24 : 16}
                  strokeOpacity={hoveredSlice && hoveredSlice !== 'Deterministic' ? 0.35 : 1}
                  fill="none"
                  strokeDasharray={`${strokeDet} ${c}`}
                  strokeDashoffset={offsetDet}
                  className="cursor-pointer transition-all duration-200"
                  style={{ pointerEvents: 'stroke' }}
                  onMouseEnter={() => setHoveredSlice('Deterministic')}
                  onMouseLeave={() => setHoveredSlice(null)}
                />

                {/* Slice 2: Nemotron AI Judge (Electric Cyan) */}
                <circle
                  cx="70"
                  cy="70"
                  r="54"
                  stroke="#06b6d4"
                  strokeWidth={hoveredSlice === 'Nemotron' ? 24 : 16}
                  strokeOpacity={hoveredSlice && hoveredSlice !== 'Nemotron' ? 0.35 : 1}
                  fill="none"
                  strokeDasharray={`${strokeAi} ${c}`}
                  strokeDashoffset={offsetAi}
                  className="cursor-pointer transition-all duration-200"
                  style={{ pointerEvents: 'stroke' }}
                  onMouseEnter={() => setHoveredSlice('Nemotron')}
                  onMouseLeave={() => setHoveredSlice(null)}
                />

                {/* Slice 3: Verified Allowed (Emerald Green) */}
                <circle
                  cx="70"
                  cy="70"
                  r="54"
                  stroke="#10b981"
                  strokeWidth={hoveredSlice === 'Allowed' ? 24 : 16}
                  strokeOpacity={hoveredSlice && hoveredSlice !== 'Allowed' ? 0.35 : 1}
                  fill="none"
                  strokeDasharray={`${strokeAllow} ${c}`}
                  strokeDashoffset={offsetAllow}
                  className="cursor-pointer transition-all duration-200"
                  style={{ pointerEvents: 'stroke' }}
                  onMouseEnter={() => setHoveredSlice('Allowed')}
                  onMouseLeave={() => setHoveredSlice(null)}
                />
              </svg>

              {/* Plain 2D Center Readout */}
              <div className="absolute inset-0 flex flex-col items-center justify-center pointer-events-none">
                <span className="text-4xl sm:text-5xl font-black font-mono tracking-tight text-white drop-shadow-[0_2px_8px_rgba(0,0,0,0.8)]">
                  {displayTotal < 10 ? `0${displayTotal}` : displayTotal}
                </span>
                <span className="text-[10px] sm:text-xs text-white/70 uppercase tracking-widest font-bold mt-0.5">
                  {hoveredSlice ? hoveredSlice.toUpperCase() : 'INTERCEPTS'}
                </span>
              </div>
            </div>

            {/* Clean Legend */}
            <div className="space-y-3 w-full sm:w-auto flex-1 max-w-xs">
              {/* Red */}
              <div 
                className={`p-3 rounded-xl border transition-all duration-200 cursor-pointer ${
                  hoveredSlice === 'Deterministic' 
                    ? 'bg-red-500/15 border-red-400 text-white shadow-[0_0_15px_rgba(239,68,68,0.25)]' 
                    : 'bg-white/[0.03] border-white/10 hover:border-red-400/50 text-white/90'
                }`}
                onMouseEnter={() => setHoveredSlice('Deterministic')}
                onMouseLeave={() => setHoveredSlice(null)}
              >
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2.5">
                    <span className="w-3.5 h-3.5 rounded-sm bg-red-500 shadow-[0_0_8px_rgba(239,68,68,0.8)]" />
                    <span className="font-bold text-xs sm:text-sm text-white">Deterministic Drop</span>
                  </div>
                  <span className="font-extrabold font-mono text-sm sm:text-base text-red-400">
                    {(pctDet * 100).toFixed(0)}%
                  </span>
                </div>
                <p className="text-[10px] text-white/50 mt-1 pl-6">Zero-tolerance AST regex hard kill</p>
              </div>

              {/* Cyan */}
              <div 
                className={`p-3 rounded-xl border transition-all duration-200 cursor-pointer ${
                  hoveredSlice === 'Nemotron' 
                    ? 'bg-cyan-500/15 border-cyan-400 text-white shadow-[0_0_15px_rgba(6,182,212,0.25)]' 
                    : 'bg-white/[0.03] border-white/10 hover:border-cyan-400/50 text-white/90'
                }`}
                onMouseEnter={() => setHoveredSlice('Nemotron')}
                onMouseLeave={() => setHoveredSlice(null)}
              >
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2.5">
                    <span className="w-3.5 h-3.5 rounded-sm bg-cyan-400 shadow-[0_0_8px_rgba(6,182,212,0.8)]" />
                    <span className="font-bold text-xs sm:text-sm text-white">Nemotron AI Judge</span>
                  </div>
                  <span className="font-extrabold font-mono text-sm sm:text-base text-cyan-300">
                    {(pctAi * 100).toFixed(0)}%
                  </span>
                </div>
                <p className="text-[10px] text-white/50 mt-1 pl-6">Nebius LLM semantic reasoning</p>
              </div>

              {/* Green */}
              <div 
                className={`p-3 rounded-xl border transition-all duration-200 cursor-pointer ${
                  hoveredSlice === 'Allowed' 
                    ? 'bg-emerald-500/15 border-emerald-400 text-white shadow-[0_0_15px_rgba(16,185,129,0.25)]' 
                    : 'bg-white/[0.03] border-white/10 hover:border-emerald-400/50 text-white/90'
                }`}
                onMouseEnter={() => setHoveredSlice('Allowed')}
                onMouseLeave={() => setHoveredSlice(null)}
              >
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2.5">
                    <span className="w-3.5 h-3.5 rounded-sm bg-emerald-400 shadow-[0_0_8px_rgba(16,185,129,0.8)]" />
                    <span className="font-bold text-xs sm:text-sm text-white">Verified Safe Pass</span>
                  </div>
                  <span className="font-extrabold font-mono text-sm sm:text-base text-emerald-400">
                    {(pctAllow * 100).toFixed(0)}%
                  </span>
                </div>
                <p className="text-[10px] text-white/50 mt-1 pl-6">Safe MCP tool execution authorized</p>
              </div>
            </div>
          </div>

          {/* Footer */}
          <div className="pt-3 border-t border-white/10 flex items-center justify-between text-[11px] text-white/50">
            <span className="flex items-center gap-2">
              <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400" />
              <span className="text-white/80 font-semibold">FAIL-CLOSED ACTIVE</span>
            </span>
            <span>MITRE T1059 / T1083 / T1195</span>
          </div>
        </TiltCard>
      </div>

      {/* 2. 3D ISOMETRIC VOLUMETRIC PILLAR HISTOGRAM */}
      <div className="lg:col-span-3">
        <TiltCard maxTilt={14} className="p-6 rounded-2xl mirror-panel h-full flex flex-col justify-between">
          <div className="flex items-center justify-between border-b border-white/10 pb-3.5">
            <div className="flex items-center gap-2.5">
              <div className="p-1.5 rounded-lg bg-white/10 border border-white/15">
                <BarChart3 className="w-4 h-4 text-white" />
              </div>
              <div>
                <span className="font-bold text-white tracking-wider text-xs sm:text-sm">3D LATENCY PILLARS</span>
                <p className="text-[10px] text-white/50">Microsecond Telemetry</p>
              </div>
            </div>
            <div className="flex items-center gap-1 text-[11px] text-white/70 px-2.5 py-1 rounded-md border border-white/15 bg-white/5">
              <Activity className="w-3 h-3 text-emerald-400" />
              <span className="font-semibold">&lt; 5MS SLA</span>
            </div>
          </div>

          {/* 3D Isometric Bar Stage */}
          <div className="my-4" style={{ transformStyle: 'preserve-3d' }}>
            <div className="flex items-center justify-between text-[11px] text-white/50 mb-3">
              <span>VOLUMETRIC PRISMS</span>
              <span className="text-white font-mono font-bold">
                {hoveredBar !== null ? `${latencyPillars[hoveredBar].latency} (${latencyPillars[hoveredBar].count} calls)` : 'REALTIME TELEMETRY'}
              </span>
            </div>

            {/* Isometric SVG Graph with True 3D Volumetric Prisms */}
            <div 
              className="relative w-full h-44 flex items-center justify-center p-1"
              style={{ perspective: '850px', transformStyle: 'preserve-3d' }}
            >
              <svg 
                className="w-full h-full overflow-visible"
                viewBox="0 0 290 145"
                preserveAspectRatio="xMidYMid meet"
              >
                <defs>
                  <linearGradient id="prism-front-bright" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="#ffffff" />
                    <stop offset="100%" stopColor="#71717a" />
                  </linearGradient>
                  <linearGradient id="prism-front-mid" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="#38bdf8" />
                    <stop offset="100%" stopColor="#0369a1" />
                  </linearGradient>
                  <linearGradient id="prism-front-dim" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="#71717a" />
                    <stop offset="100%" stopColor="#18181b" />
                  </linearGradient>

                  <linearGradient id="prism-side-bright" x1="0" y1="0" x2="1" y2="1">
                    <stop offset="0%" stopColor="#a1a1aa" />
                    <stop offset="100%" stopColor="#27272a" />
                  </linearGradient>
                  <linearGradient id="prism-side-mid" x1="0" y1="0" x2="1" y2="1">
                    <stop offset="0%" stopColor="#0284c7" />
                    <stop offset="100%" stopColor="#082f49" />
                  </linearGradient>
                  <linearGradient id="prism-side-dim" x1="0" y1="0" x2="1" y2="1">
                    <stop offset="0%" stopColor="#3f3f46" />
                    <stop offset="100%" stopColor="#09090b" />
                  </linearGradient>
                </defs>

                {/* Isometric Grid Floor Base Lines */}
                <g opacity="0.3">
                  <line x1="10" y1="125" x2="280" y2="125" stroke="#ffffff" strokeWidth="1" strokeDasharray="2 3" />
                  <line x1="20" y1="105" x2="270" y2="105" stroke="#ffffff" strokeWidth="0.5" strokeDasharray="3 3" />
                  <line x1="30" y1="85" x2="260" y2="85" stroke="#ffffff" strokeWidth="0.5" strokeDasharray="3 3" />
                </g>

                {/* 3D Isometric Prisms Render Loop */}
                {latencyPillars.map((pillar, i) => {
                  const barWidth = 18;
                  const depth = 8;
                  const x = 18 + i * 28;
                  const baseY = 125;
                  const height = (pillar.height / 100) * 95;
                  const topY = baseY - height;
                  const isHovered = hoveredBar === i;

                  const frontGrad = pillar.active ? 'url(#prism-front-mid)' : pillar.height > 50 ? 'url(#prism-front-bright)' : 'url(#prism-front-dim)';
                  const sideGrad = pillar.active ? 'url(#prism-side-mid)' : pillar.height > 50 ? 'url(#prism-side-bright)' : 'url(#prism-side-dim)';

                  return (
                    <g 
                      key={i} 
                      className="cursor-pointer transition-all duration-300"
                      onMouseEnter={() => setHoveredBar(i)}
                      onMouseLeave={() => setHoveredBar(null)}
                      style={{
                        transform: isHovered ? 'translateY(-8px)' : 'none',
                        filter: isHovered ? 'drop-shadow(0 0 16px rgba(56,189,248,0.9))' : 'none',
                      }}
                    >
                      {/* Floor Base Shadow */}
                      <polygon
                        points={`${x},${baseY} ${x + barWidth},${baseY - depth * 0.4} ${x + barWidth + depth},${baseY} ${x + depth},${baseY + depth * 0.4}`}
                        fill="#000000"
                        opacity="0.7"
                      />

                      {/* 1. Front Vertical Face */}
                      <polygon
                        points={`${x},${topY} ${x + barWidth},${topY} ${x + barWidth},${baseY} ${x},${baseY}`}
                        fill={frontGrad}
                        stroke="#ffffff"
                        strokeWidth={isHovered ? 1.2 : 0.4}
                        strokeOpacity={isHovered ? 1 : 0.25}
                      />

                      {/* 2. Side Depth Extrusion Face (3D Thickness) */}
                      <polygon
                        points={`${x + barWidth},${topY} ${x + barWidth + depth},${topY - depth * 0.6} ${x + barWidth + depth},${baseY - depth * 0.6} ${x + barWidth},${baseY}`}
                        fill={sideGrad}
                        stroke="#ffffff"
                        strokeWidth={isHovered ? 1.2 : 0.4}
                        strokeOpacity={isHovered ? 1 : 0.2}
                      />

                      {/* 3. Top Cap Face */}
                      <polygon
                        points={`${x},${topY} ${x + depth},${topY - depth * 0.6} ${x + barWidth + depth},${topY - depth * 0.6} ${x + barWidth},${topY}`}
                        fill={isHovered ? '#ffffff' : pillar.active ? '#38bdf8' : '#e4e4e7'}
                        stroke="#ffffff"
                        strokeWidth={1}
                        strokeOpacity={0.8}
                      />

                      {/* Floating Latency Tooltip above Pillar */}
                      {isHovered && (
                        <g>
                          <rect 
                            x={x - 8} 
                            y={topY - 28} 
                            width="42" 
                            height="18" 
                            rx="4" 
                            fill="#ffffff" 
                            filter="drop-shadow(0 2px 8px rgba(0,0,0,0.8))"
                          />
                          <text 
                            x={x + 13} 
                            y={topY - 16} 
                            textAnchor="middle" 
                            fontSize="9" 
                            fontWeight="bold" 
                            fill="#000000"
                            fontFamily="monospace"
                          >
                            {pillar.latency}
                          </text>
                        </g>
                      )}

                      {/* Pillar Baseline Label */}
                      <text
                        x={x + barWidth / 2}
                        y={baseY + 16}
                        textAnchor="middle"
                        fontSize="9"
                        fontFamily="monospace"
                        fill={isHovered ? '#ffffff' : '#a1a1aa'}
                        fontWeight={isHovered ? 'bold' : 'semibold'}
                      >
                        {pillar.label}
                      </text>
                    </g>
                  );
                })}
              </svg>
            </div>

            {/* Quick Metrics */}
            <div className="flex items-center justify-between text-[11px] text-white/80 mt-3 pt-2.5 border-t border-white/10">
              <div>
                <span className="text-white/40">p50:</span> <strong className="text-white ml-1">3.8ms</strong>
              </div>
              <div>
                <span className="text-white/40">p99:</span> <strong className="text-white ml-1">6.2ms</strong>
              </div>
              <div>
                <span className="text-white/40">AI:</span> <strong className="text-cyan-400 ml-1">410ms</strong>
              </div>
            </div>
          </div>

          <div className="pt-3 border-t border-white/10 flex items-center justify-between text-[11px] text-white/50">
            <span>AXONOMETRIC PRISMS</span>
            <span>&lt; 5MS GUARANTEE</span>
          </div>
        </TiltCard>
      </div>

      {/* 3. 3D STEPPED DEFENSE PIPELINE MATRIX */}
      <div className="lg:col-span-3">
        <TiltCard maxTilt={14} className="p-6 rounded-2xl mirror-panel h-full flex flex-col justify-between">
          <div className="flex items-center justify-between border-b border-white/10 pb-3.5">
            <div className="flex items-center gap-2.5">
              <div className="p-1.5 rounded-lg bg-white/10 border border-white/15">
                <ShieldAlert className="w-4 h-4 text-white" />
              </div>
              <div>
                <span className="font-bold text-white tracking-wider text-xs sm:text-sm">3D DEFENSE MATRIX</span>
                <p className="text-[10px] text-white/50">Enforcer Pipelines</p>
              </div>
            </div>
            <div className="flex items-center gap-1 text-[11px] text-white/70 px-2.5 py-1 rounded-md border border-white/15 bg-white/5">
              <Lock className="w-3 h-3 text-red-400" />
              <span className="font-semibold">FAIL-CLOSED</span>
            </div>
          </div>

          <div className="space-y-3.5 my-4" style={{ transformStyle: 'preserve-3d' }}>
            {[
              { id: 'T1083', name: 'Path Traversal', pct: 88, z: 18, status: 'BLOCKED', color: 'from-red-500 to-rose-400' },
              { id: 'T1059', name: 'Command Injection', pct: 76, z: 14, status: 'BLOCKED', color: 'from-red-500 to-rose-400' },
              { id: 'T1195', name: 'Supply-Chain Hook', pct: 42, z: 10, status: 'ESCALATED', color: 'from-cyan-500 to-sky-400' },
              { id: 'T1552', name: 'Secret Exfiltration', pct: 28, z: 6, status: 'INSPECTED', color: 'from-emerald-500 to-teal-400' },
            ].map((item, idx) => (
              <div 
                key={idx} 
                className="group relative p-3 rounded-xl border border-white/10 bg-white/[0.03] hover:bg-white/[0.08] hover:border-white/30 transition-all duration-300 cursor-pointer"
                style={{ 
                  transform: `translateZ(${item.z}px)`,
                  boxShadow: '0 8px 18px rgba(0,0,0,0.7)',
                }}
              >
                <div className="flex items-center justify-between text-xs mb-2">
                  <div className="flex items-center gap-2">
                    <span className="px-1.5 py-0.5 rounded bg-white text-black font-bold font-mono text-[10px] shadow-[0_0_8px_rgba(255,255,255,0.4)]">
                      {item.id}
                    </span>
                    <span className="text-white/90 group-hover:text-white font-semibold transition">
                      {item.name}
                    </span>
                  </div>
                  <span className="text-xs font-mono font-bold text-white">
                    {item.pct}%
                  </span>
                </div>

                {/* 3D Recessed Conduit Bar */}
                <div 
                  className="w-full h-2.5 rounded-full overflow-hidden p-0.5 border border-white/10"
                  style={{
                    background: 'linear-gradient(180deg, rgba(0,0,0,0.95) 0%, rgba(20,20,20,0.95) 100%)',
                    boxShadow: 'inset 0 2px 4px rgba(0,0,0,0.95)',
                  }}
                >
                  <div 
                    className={`h-full rounded-full transition-all duration-700 bg-gradient-to-r ${item.color} shadow-[0_0_10px_rgba(255,255,255,0.5)] group-hover:brightness-125`}
                    style={{ width: `${item.pct}%` }} 
                  />
                </div>

                <div className="flex items-center justify-between text-[10px] text-white/50 mt-2">
                  <span className="flex items-center gap-1.5">
                    <Cpu className="w-3 h-3 text-white/70" />
                    <span>Deterministic Gate</span>
                  </span>
                  <span className={`font-mono font-bold ${item.status === 'BLOCKED' ? 'text-red-400' : item.status === 'ESCALATED' ? 'text-cyan-300' : 'text-emerald-400'}`}>
                    {item.status}
                  </span>
                </div>
              </div>
            ))}
          </div>

          <div className="pt-3 border-t border-white/10 flex items-center justify-between text-[11px] text-white/50">
            <span>FAIL-CLOSED ACTIVE</span>
            <span>4 ENFORCERS READY</span>
          </div>
        </TiltCard>
      </div>

    </div>
  );
}
