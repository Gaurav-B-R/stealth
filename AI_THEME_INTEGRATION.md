# AI Theme Integration Guide

## Available Open-Source Libraries for AI Themes

### 1. **Particles.js / TSParticles** ⭐ Recommended
**For:** Animated particle backgrounds, holographic effects
- **CDN:** `https://cdn.jsdelivr.net/particles.js/2.0.0/particles.min.js`
- **Use case:** Background particle effects, floating elements
- **Free:** Yes, MIT License

### 2. **Animate.css**
**For:** Ready-made animations
- **CDN:** `https://cdnjs.cloudflare.com/ajax/libs/animate.css/4.1.1/animate.min.css`
- **Use case:** Fade-in, sli animationsde-in, pulse
- **Free:** Yes, MIT License

### 3. **Three.js**
**For:** 3D holographic avatars, 3D effects
- **CDN:** `https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js`
- **Use case:** 3D avatar rendering, holographic displays
- **Free:** Yes, MIT License

### 4. **AOS (Animate On Scroll)**
**For:** Scroll-triggered animations
- **CDN:** `https://unpkg.com/aos@next/dist/aos.css` and `https://unpkg.com/aos@next/dist/aos.js`
- **Use case:** Elements animate when scrolling into view
- **Free:** Yes, MIT License

### 5. **GSAP (GreenSock Animation Platform)**
**For:** Advanced, smooth animations
- **CDN:** `https://cdnjs.cloudflare.com/ajax/libs/gsap/3.12.2/gsap.min.js`
- **Use case:** Complex animation sequences
- **Free:** Yes (limited features), Commercial license for full features

### 6. **Glassmorphism CSS Libraries**
**For:** Pre-built glassmorphism utilities
- **Resources:** CSS custom properties, no library needed (already implemented)

## Quick Integration Examples

### Option 1: Add Particles.js (Easiest)
```html
<!-- Add to index.html before </body> -->
<script src="https://cdn.jsdelivr.net/particles.js/2.0.0/particles.min.js"></script>
<div id="particles-js"></div>

<script>
particlesJS('particles-js', {
  particles: {
    number: { value: 80 },
    color: { value: '#3b82f6' },
    shape: { type: 'circle' },
    opacity: { value: 0.5 },
    size: { value: 3 },
    move: { enable: true, speed: 2 }
  }
});
</script>
```

### Option 2: Add Animate.css
```html
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/animate.css/4.1.1/animate.min.css">

<!-- Use in HTML -->
<div class="animate__animated animate__fadeInUp">Content</div>
```

### Option 3: Add AOS (Scroll Animations)
```html
<link href="https://unpkg.com/aos@2.3.1/dist/aos.css" rel="stylesheet">
<script src="https://unpkg.com/aos@2.3.1/dist/aos.js"></script>

<script>
  AOS.init();
</script>

<!-- Use in HTML -->
<div data-aos="fade-up" data-aos-duration="1000">Content</div>
```

## Paid Templates (If Budget Allows)

1. **Daily AI Template** - $49-79 (Webflow)
2. **Futur Studio** - Premium pricing (Webflow)
3. **Visily AI Template** - Custom pricing

## Recommendation

For your current setup, I recommend:
1. **Particles.js** - Add dynamic background particles
2. **Animate.css** - Quick animations for panels/avatar
3. **Keep custom CSS** - Your current glassmorphism implementation is good

Would you like me to integrate any of these into your homepage?

