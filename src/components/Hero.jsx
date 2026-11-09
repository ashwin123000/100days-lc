import { motion, useReducedMotion } from 'motion/react'
import Button from './Button.jsx'
import logo from '../assets/mlsc-logo-transparent.png'

function Hero({ onStartSolving }) {
  const shouldReduceMotion = useReducedMotion()
  const entrance = (delay) =>
    shouldReduceMotion
      ? {}
      : {
          initial: { opacity: 0, y: 16 },
          animate: { opacity: 1, y: 0 },
          transition: { duration: 0.65, delay, ease: [0.22, 1, 0.36, 1] },
        }

  return (
    <section className="hero-section" id="home" aria-labelledby="hero-title">
      <div className="hero-content">
        <motion.div className="hero-mark" {...entrance(0.05)}>
          <img src={logo} alt="Microsoft Learn Student Ambassador badge" />
        </motion.div>

        <motion.p className="eyebrow" {...entrance(0.12)}>
          MICROSOFT LEARN STUDENT CHAPTER <span aria-hidden="true">/</span> THE CODING CHALLENGE
        </motion.p>

        <motion.h1 id="hero-title" {...entrance(0.2)}>
          Microsoft Learn
          <br />
          <span>Student Chapter</span>
        </motion.h1>

        <motion.p className="hero-subtitle" {...entrance(0.28)}>
          Learn. Practice. Compete. Grow.
        </motion.p>

        <motion.p className="hero-tagline" {...entrance(0.34)}>
          100 Days. Countless Problems. One Stronger You.
        </motion.p>

        <motion.div className="hero-description" id="about" {...entrance(0.42)}>
          <p>
            Driven by the spirit of continuous learning, MLSC brings aspiring developers together
            to strengthen their problem-solving skills through consistent practice.
          </p>
          <p>
            Take on the 100 Days of LeetCode Challenge, track your progress, and grow into a better
            engineer.
          </p>
        </motion.div>

        <motion.div className="hero-action" {...entrance(0.5)}>
          <Button onClick={onStartSolving}>
            Start Solving – 100 Days of LeetCode
          </Button>
        </motion.div>
      </div>
    </section>
  )
}

export default Hero
