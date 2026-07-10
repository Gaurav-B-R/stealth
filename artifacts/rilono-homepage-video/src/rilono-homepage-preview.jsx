import React from 'react';
import {
  AbsoluteFill,
  Easing,
  interpolate,
  spring,
  useCurrentFrame,
  useVideoConfig,
} from 'remotion';

const C = {
  ink: '#111426',
  muted: '#69718a',
  blue: '#5d5cf5',
  violet: '#9556ee',
  pink: '#e8429d',
  cyan: '#1fc5e8',
  green: '#16a879',
  amber: '#f1a323',
  panel: 'rgba(255,255,255,0.88)',
  line: 'rgba(67,72,116,0.13)',
};

const FONT = '"Avenir Next", "Helvetica Neue", sans-serif';

const clamp = {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'};

const sceneOpacity = (frame, start, end, fadeOutStart, fadeOutEnd) =>
  interpolate(frame, [start, end, fadeOutStart, fadeOutEnd], [0, 1, 1, 0], clamp);

const rise = (frame, start, distance = 26) =>
  interpolate(frame, [start, start + 24], [distance, 0], {
    ...clamp,
    easing: Easing.out(Easing.cubic),
  });

const BrandMark = ({size = 64, dark = true}) => (
  <div
    style={{
      width: size,
      height: size,
      borderRadius: size * 0.24,
      display: 'grid',
      placeItems: 'center',
      background: dark ? '#10121c' : '#fff',
      color: dark ? '#fff' : '#111426',
      fontFamily: FONT,
      fontWeight: 900,
      fontSize: size * 0.58,
      letterSpacing: '-0.08em',
      boxShadow: '0 18px 50px rgba(53,52,130,.18)',
    }}
  >
    R
  </div>
);

const SparkIcon = ({size = 28, color = C.blue}) => (
  <svg width={size} height={size} viewBox="0 0 32 32" fill="none">
    <path d="M16 2c1.4 8.1 5.9 12.6 14 14-8.1 1.4-12.6 5.9-14 14C14.6 21.9 10.1 17.4 2 16 10.1 14.6 14.6 10.1 16 2Z" fill={color}/>
    <circle cx="26" cy="6" r="3" fill={C.pink}/>
  </svg>
);

const CheckIcon = ({color = C.green, size = 22}) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none">
    <circle cx="12" cy="12" r="10" fill={color}/>
    <path d="m7.5 12.2 3 3.1 6.3-6.7" stroke="#fff" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round"/>
  </svg>
);

const MicIcon = ({size = 28}) => (
  <svg width={size} height={size} viewBox="0 0 32 32" fill="none">
    <rect x="11" y="3" width="10" height="17" rx="5" stroke="currentColor" strokeWidth="2.4"/>
    <path d="M7 15c0 5 3.7 9 9 9s9-4 9-9M16 24v5M11 29h10" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round"/>
  </svg>
);

const PlaneIcon = ({size = 34}) => (
  <svg width={size} height={size} viewBox="0 0 40 40" fill="none">
    <path d="M35 7 24 18 8 12l-3 3 13 9-7 7-5-1-2 2 7 4 4-1-1-5 7-7 9 13 3-3-6-16L38 10c2-3 0-5-3-3Z" fill="currentColor"/>
  </svg>
);

const Pill = ({children, color = C.blue}) => (
  <div style={{padding: '9px 15px', borderRadius: 999, background: `${color}14`, color, border: `1px solid ${color}38`, fontWeight: 750, fontSize: 14}}>
    {children}
  </div>
);

const Ambient = ({frame}) => {
  const drift = Math.sin(frame / 55) * 18;
  const drift2 = Math.cos(frame / 68) * 22;
  return (
    <AbsoluteFill style={{overflow: 'hidden', background: 'linear-gradient(145deg,#fbfbff 0%,#f1f4ff 58%,#fff7fb 100%)'}}>
      <div style={{position: 'absolute', width: 520, height: 520, borderRadius: '50%', left: -190 + drift, top: -200 + drift2, background: 'radial-gradient(circle,rgba(93,92,245,.18),rgba(93,92,245,0) 68%)'}}/>
      <div style={{position: 'absolute', width: 590, height: 590, borderRadius: '50%', right: -240 - drift2, bottom: -290 + drift, background: 'radial-gradient(circle,rgba(232,66,157,.15),rgba(232,66,157,0) 68%)'}}/>
      <div style={{position: 'absolute', inset: 0, opacity: .22, backgroundImage: 'linear-gradient(rgba(83,88,140,.08) 1px,transparent 1px),linear-gradient(90deg,rgba(83,88,140,.08) 1px,transparent 1px)', backgroundSize: '44px 44px', maskImage: 'linear-gradient(to bottom,transparent,black 18%,black 82%,transparent)'}}/>
    </AbsoluteFill>
  );
};

const SceneOne = ({frame, fps}) => {
  const opacity = sceneOpacity(frame, 0, 18, 120, 148);
  const scale = spring({frame, fps, config: {damping: 14, mass: .8, stiffness: 110}});
  const chip = interpolate(frame, [35, 58], [0, 1], clamp);
  return (
    <AbsoluteFill style={{opacity, alignItems: 'center', justifyContent: 'center', fontFamily: FONT}}>
      <div style={{display: 'flex', alignItems: 'center', gap: 18, transform: `scale(${.86 + scale * .14})`, marginBottom: 34}}>
        <BrandMark size={68}/>
        <div style={{fontWeight: 850, fontSize: 43, letterSpacing: '-.045em', color: C.ink}}>Rilono</div>
      </div>
      <div style={{opacity: chip, transform: `translateY(${rise(frame, 35, 16)}px)`, display: 'flex', alignItems: 'center', gap: 9, padding: '10px 17px', borderRadius: 999, color: C.blue, background: 'rgba(93,92,245,.08)', border: '1px solid rgba(93,92,245,.18)', fontWeight: 760, fontSize: 15}}>
        <SparkIcon size={20}/> AI-powered student visa platform
      </div>
      <div style={{fontWeight: 900, fontSize: 68, letterSpacing: '-.055em', lineHeight: 1.04, color: C.ink, textAlign: 'center', maxWidth: 980, marginTop: 24, opacity: interpolate(frame,[52,76],[0,1],clamp), transform: `translateY(${rise(frame, 52, 30)}px)`}}>
        Student visas, without the guesswork.
      </div>
      <div style={{color: C.muted, fontSize: 22, marginTop: 20, opacity: interpolate(frame,[72,94],[0,1],clamp), transform: `translateY(${rise(frame,72,20)}px)`}}>
        One guided path from your first document to visa day.
      </div>
    </AbsoluteFill>
  );
};

const Roadmap = ({frame, start}) => {
  const stages = [
    ['01', 'Profile'], ['02', 'Admission'], ['03', 'Documents'], ['04', 'Interview'], ['05', 'Visa'],
  ];
  const progress = interpolate(frame, [start + 25, start + 150], [0, 1], clamp);
  return (
    <div style={{position: 'relative', marginTop: 32, padding: '32px 26px 18px'}}>
      <div style={{position: 'absolute', left: 62, right: 62, top: 53, height: 4, borderRadius: 8, background: '#e8e9f4'}}>
        <div style={{width: `${progress * 100}%`, height: '100%', borderRadius: 8, background: `linear-gradient(90deg,${C.blue},${C.pink})`, boxShadow: '0 0 18px rgba(113,83,241,.35)'}}/>
      </div>
      <div style={{position: 'relative', display: 'flex', justifyContent: 'space-between'}}>
        {stages.map(([num, label], i) => {
          const local = interpolate(frame, [start + 12 + i * 16, start + 32 + i * 16], [0, 1], clamp);
          const active = progress >= i / (stages.length - 1);
          return (
            <div key={label} style={{width: 106, textAlign: 'center', opacity: local, transform: `translateY(${(1-local)*12}px)`}}>
              <div style={{margin: '0 auto 13px', width: 45, height: 45, borderRadius: '50%', display: 'grid', placeItems: 'center', color: active ? '#fff' : '#858ca2', background: active ? `linear-gradient(135deg,${C.blue},${C.violet})` : '#fff', border: active ? 'none' : '2px solid #e1e4ef', boxShadow: active ? '0 10px 24px rgba(93,92,245,.28)' : 'none', fontSize: 13, fontWeight: 850}}>{num}</div>
              <div style={{fontSize: 14, fontWeight: active ? 800 : 650, color: active ? C.ink : '#858ca2'}}>{label}</div>
            </div>
          );
        })}
      </div>
    </div>
  );
};

const SceneTwo = ({frame}) => {
  const start = 125;
  const opacity = sceneOpacity(frame, start, start + 28, 292, 324);
  return (
    <AbsoluteFill style={{opacity, fontFamily: FONT, padding: '72px 74px', flexDirection: 'row', alignItems: 'center', gap: 66}}>
      <div style={{width: 430, transform: `translateX(${interpolate(frame,[start,start+28],[-45,0],clamp)}px)`}}>
        <Pill>PERSONALIZED ROADMAP</Pill>
        <h2 style={{fontSize: 54, lineHeight: 1.06, letterSpacing: '-.05em', margin: '22px 0 18px', color: C.ink}}>Know exactly what comes next.</h2>
        <p style={{fontSize: 20, lineHeight: 1.55, color: C.muted, margin: 0}}>Rilono builds a stage-by-stage journey for your destination, visa type, university and intake.</p>
        <div style={{display: 'flex', gap: 10, marginTop: 27}}><Pill color={C.green}>US</Pill><Pill color={C.violet}>UK</Pill><Pill color={C.pink}>Canada</Pill><Pill color={C.cyan}>Australia</Pill><Pill color={C.amber}>Germany</Pill></div>
      </div>
      <div style={{width: 650, borderRadius: 30, padding: '29px 30px 28px', background: C.panel, border: `1px solid ${C.line}`, boxShadow: '0 30px 90px rgba(45,49,105,.14)', transform: `translateY(${rise(frame,start+8,34)}px) scale(${interpolate(frame,[start,start+32],[.96,1],clamp)})`}}>
        <div style={{display: 'flex', alignItems: 'center', justifyContent: 'space-between'}}>
          <div><div style={{fontSize: 13, fontWeight: 850, color: C.blue, letterSpacing: '.11em'}}>YOUR VISA JOURNEY</div><div style={{fontSize: 25, fontWeight: 850, color: C.ink, marginTop: 5}}>United States - F-1 Student Visa</div></div>
          <div style={{width: 44, height: 44, display: 'grid', placeItems: 'center', borderRadius: 15, background: '#eef0ff', color: C.blue}}><PlaneIcon size={25}/></div>
        </div>
        <Roadmap frame={frame} start={start}/>
        <div style={{marginTop: 17, padding: '18px 20px', borderRadius: 18, background: 'linear-gradient(110deg,rgba(93,92,245,.09),rgba(232,66,157,.07))', border: '1px solid rgba(93,92,245,.15)', display: 'flex', alignItems: 'center', gap: 14}}>
          <SparkIcon size={25}/><div><b style={{color: C.ink}}>Next step:</b><span style={{color: C.muted}}> Upload and validate your starter documents.</span></div>
        </div>
      </div>
    </AbsoluteFill>
  );
};

const DocRow = ({frame, start, title, status, tone, delay}) => {
  const p = spring({frame: frame - start - delay, fps: 30, config: {damping: 15, stiffness: 120}});
  const scan = interpolate(frame, [start + 42 + delay, start + 78 + delay], [0, 1], clamp);
  const color = tone === 'green' ? C.green : tone === 'amber' ? C.amber : C.blue;
  return (
    <div style={{position: 'relative', overflow: 'hidden', display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '17px 18px', borderRadius: 17, background: '#fff', border: `1px solid ${C.line}`, opacity: p, transform: `translateX(${(1-p)*36}px)`}}>
      <div style={{display: 'flex', alignItems: 'center', gap: 13}}>
        <div style={{width: 35, height: 42, borderRadius: 8, background: '#f0f2fb', border: '1px solid #dde0ed', position: 'relative'}}><div style={{position: 'absolute', left: 8, right: 8, top: 12, height: 3, borderRadius: 3, background: '#bfc5d7', boxShadow: '0 7px 0 #d1d5e2,0 14px 0 #d1d5e2'}}/></div>
        <div><div style={{fontWeight: 800, color: C.ink, fontSize: 16}}>{title}</div><div style={{color: C.muted, fontSize: 13, marginTop: 3}}>AI document review</div></div>
      </div>
      <div style={{display: 'flex', alignItems: 'center', gap: 8, color, fontWeight: 800, fontSize: 13, opacity: scan}}><CheckIcon color={color} size={20}/>{status}</div>
      <div style={{position: 'absolute', left: `${scan*118-18}%`, top: 0, bottom: 0, width: 50, background: 'linear-gradient(90deg,transparent,rgba(93,92,245,.16),transparent)', transform: 'skewX(-15deg)'}}/>
    </div>
  );
};

const SceneThree = ({frame}) => {
  const start = 300;
  const opacity = sceneOpacity(frame, start, start + 28, 510, 542);
  return (
    <AbsoluteFill style={{opacity, fontFamily: FONT, padding: '65px 74px', flexDirection: 'row', alignItems: 'center', gap: 70}}>
      <div style={{width: 610, borderRadius: 30, padding: 30, background: C.panel, border: `1px solid ${C.line}`, boxShadow: '0 30px 90px rgba(45,49,105,.14)'}}>
        <div style={{display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 21}}><div><div style={{fontSize: 13, fontWeight: 850, color: C.blue, letterSpacing: '.11em'}}>DOCUMENT HEALTH</div><div style={{fontSize: 25, fontWeight: 850, color: C.ink, marginTop: 5}}>3 documents reviewed</div></div><SparkIcon size={34}/></div>
        <div style={{display: 'grid', gap: 11}}>
          <DocRow frame={frame} start={start} title="Passport" status="Validated" tone="green" delay={0}/>
          <DocRow frame={frame} start={start} title="Admission letter" status="Validated" tone="green" delay={12}/>
          <DocRow frame={frame} start={start} title="Bank statement" status="Review needed" tone="amber" delay={24}/>
        </div>
        <div style={{marginTop: 18, padding: '15px 17px', borderRadius: 16, background: 'rgba(241,163,35,.09)', border: '1px solid rgba(241,163,35,.22)', color: '#82590d', fontSize: 14, lineHeight: 1.45, opacity: interpolate(frame,[start+95,start+120],[0,1],clamp)}}><b>Rilono AI found a timeline risk:</b> Your financial evidence may be too old for your intended filing date.</div>
      </div>
      <div style={{width: 430}}>
        <Pill color={C.pink}>RED-FLAG CHECKS</Pill>
        <h2 style={{fontSize: 53, lineHeight: 1.06, letterSpacing: '-.05em', margin: '22px 0 18px', color: C.ink}}>Catch issues before they become refusals.</h2>
        <p style={{fontSize: 20, lineHeight: 1.55, color: C.muted, margin: 0}}>Dates, missing pages, identity mismatches and financial gaps are surfaced while you still have time to fix them.</p>
      </div>
    </AbsoluteFill>
  );
};

const ChatBubble = ({children, right = false, accent = false, opacity = 1, y = 0}) => (
  <div style={{display: 'flex', justifyContent: right ? 'flex-end' : 'flex-start', opacity, transform: `translateY(${y}px)`}}>
    <div style={{maxWidth: right ? 410 : 480, padding: '15px 18px', borderRadius: right ? '18px 18px 5px 18px' : '18px 18px 18px 5px', background: right ? `linear-gradient(135deg,${C.blue},${C.violet})` : accent ? 'rgba(22,168,121,.09)' : '#f3f4fa', color: right ? '#fff' : C.ink, fontSize: 16, lineHeight: 1.45, border: right ? 'none' : `1px solid ${accent ? 'rgba(22,168,121,.20)' : C.line}`}}>{children}</div>
  </div>
);

const SceneFour = ({frame}) => {
  const start = 520;
  const opacity = sceneOpacity(frame, start, start + 26, 704, 736);
  const a = interpolate(frame,[start+30,start+52],[0,1],clamp);
  const b = interpolate(frame,[start+74,start+96],[0,1],clamp);
  const c = interpolate(frame,[start+120,start+142],[0,1],clamp);
  const pulse = 1 + Math.sin(frame/6) * .05;
  return (
    <AbsoluteFill style={{opacity, fontFamily: FONT, padding: '66px 74px', flexDirection: 'row', alignItems: 'center', gap: 70}}>
      <div style={{width: 420}}>
        <Pill color={C.violet}>AI MOCK INTERVIEWS</Pill>
        <h2 style={{fontSize: 54, lineHeight: 1.06, letterSpacing: '-.05em', margin: '22px 0 18px', color: C.ink}}>Practice like it is the real interview.</h2>
        <p style={{fontSize: 20, lineHeight: 1.55, color: C.muted, margin: 0}}>Answer by voice or chat. Get instant, practical feedback tailored to your story and destination.</p>
      </div>
      <div style={{width: 650, borderRadius: 30, overflow: 'hidden', background: C.panel, border: `1px solid ${C.line}`, boxShadow: '0 30px 90px rgba(45,49,105,.14)'}}>
        <div style={{padding: '20px 24px', display: 'flex', justifyContent: 'space-between', alignItems: 'center', background: 'linear-gradient(110deg,#1d2142,#29234d)', color: '#fff'}}><div><div style={{fontWeight: 850, fontSize: 19}}>Mock Interview</div><div style={{opacity: .65, fontSize: 12, marginTop: 3}}>F-1 student visa</div></div><div style={{display: 'flex', alignItems: 'center', gap: 8, padding: '8px 12px', borderRadius: 999, background: 'rgba(255,255,255,.10)', transform: `scale(${pulse})`}}><MicIcon size={18}/><span style={{fontSize: 12, fontWeight: 800}}>MIC READY</span></div></div>
        <div style={{padding: 24, display: 'grid', gap: 13, minHeight: 345}}>
          <ChatBubble opacity={a} y={(1-a)*18}><b>Visa Officer:</b><br/>Why did you choose this university and program?</ChatBubble>
          <ChatBubble right opacity={b} y={(1-b)*18}>The curriculum aligns with my goal of building secure, scalable software systems...</ChatBubble>
          <ChatBubble accent opacity={c} y={(1-c)*18}><div style={{display: 'flex', gap: 10}}><SparkIcon size={22} color={C.green}/><div><b style={{color: C.green}}>Strong foundation.</b><br/><span style={{color: C.muted}}>Add one specific course and connect it to your post-study plan.</span></div></div></ChatBubble>
        </div>
      </div>
    </AbsoluteFill>
  );
};

const SceneFive = ({frame, fps}) => {
  const start = 710;
  const opacity = interpolate(frame,[start,start+28],[0,1],clamp);
  const logo = spring({frame:frame-start-10,fps,config:{damping:14,stiffness:100}});
  const countries = ['UNITED STATES','UNITED KINGDOM','CANADA','AUSTRALIA','GERMANY'];
  return (
    <AbsoluteFill style={{opacity, fontFamily: FONT, alignItems: 'center', justifyContent: 'center', textAlign: 'center'}}>
      <div style={{display: 'flex', alignItems: 'center', gap: 16, transform: `scale(${.82+logo*.18})`}}><BrandMark size={62}/><div style={{fontSize: 40, fontWeight: 900, letterSpacing: '-.045em', color: C.ink}}>Rilono</div></div>
      <h2 style={{fontSize: 64, lineHeight: 1.04, letterSpacing: '-.055em', color: C.ink, margin: '30px 0 15px', maxWidth: 930, opacity: interpolate(frame,[start+36,start+60],[0,1],clamp), transform:`translateY(${rise(frame,start+36,25)}px)`}}>Your visa journey. Clearer, safer, more confident.</h2>
      <p style={{fontSize: 21, color: C.muted, margin: 0, opacity: interpolate(frame,[start+58,start+80],[0,1],clamp)}}>Organize. Check. Prepare. Move forward.</p>
      <div style={{display: 'flex', gap: 10, marginTop: 30}}>{countries.map((country,i)=><div key={country} style={{padding:'10px 14px',borderRadius:999,border:`1px solid ${C.line}`,background:'rgba(255,255,255,.72)',color:C.muted,fontSize:11,fontWeight:850,letterSpacing:'.07em',opacity:interpolate(frame,[start+70+i*8,start+90+i*8],[0,1],clamp),transform:`translateY(${rise(frame,start+70+i*8,15)}px)`}}>{country}</div>)}</div>
      <div style={{marginTop: 35, padding: '14px 25px', borderRadius: 14, color: '#fff', fontSize: 18, fontWeight: 850, background: `linear-gradient(110deg,${C.blue},${C.violet},${C.pink})`, boxShadow: '0 17px 38px rgba(111,72,226,.28)', opacity: interpolate(frame,[start+118,start+145],[0,1],clamp), transform:`translateY(${rise(frame,start+118,18)}px)`}}>Start your journey at rilono.com</div>
      <div style={{position:'absolute',bottom:23,fontSize:11,color:'#9ba1b4',letterSpacing:'.04em'}}>AI guidance supports preparation and does not guarantee a visa decision.</div>
    </AbsoluteFill>
  );
};

export const RilonoHomepagePreview = () => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  return (
    <AbsoluteFill style={{fontFamily: FONT, color: C.ink}}>
      <Ambient frame={frame}/>
      <SceneOne frame={frame} fps={fps}/>
      <SceneTwo frame={frame}/>
      <SceneThree frame={frame}/>
      <SceneFour frame={frame}/>
      <SceneFive frame={frame} fps={fps}/>
      <div style={{position:'absolute',left:30,top:27,display:'flex',alignItems:'center',gap:10,opacity:frame<105?0:0.58}}><BrandMark size={31}/><span style={{fontFamily:FONT,fontSize:15,fontWeight:850,color:C.ink}}>Rilono AI</span></div>
    </AbsoluteFill>
  );
};
