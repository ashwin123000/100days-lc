import { ArrowRight } from 'lucide-react'
import { motion, useReducedMotion } from 'motion/react'

function Button({ children, onClick }) {
  const shouldReduceMotion = useReducedMotion()

  return (
    <motion.button
      className="primary-button"
      type="button"
      onClick={onClick}
      whileHover={shouldReduceMotion ? undefined : { y: -2 }}
      whileTap={shouldReduceMotion ? undefined : { scale: 0.98 }}
    >
      <span>{children}</span>
      <ArrowRight aria-hidden="true" size={19} strokeWidth={2} />
    </motion.button>
  )
}

export default Button
