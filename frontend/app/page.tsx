'use client'

import { useState } from 'react'
import { motion } from 'framer-motion'
import { 
  Rocket, 
  Brain, 
  Linkedin, 
  Zap, 
  Users, 
  CheckCircle,
  ArrowRight,
  Play
} from 'lucide-react'
import Link from 'next/link'

export default function HomePage() {
  const [isPlaying, setIsPlaying] = useState(false)

  const features = [
    {
      icon: Brain,
      title: 'AI-Powered Generation',
      description: 'Create professional job descriptions using advanced AI models'
    },
    {
      icon: Linkedin,
      title: 'LinkedIn Integration',
      description: 'Automatically post jobs to LinkedIn with proper formatting'
    },
    {
      icon: Zap,
      title: 'Smart Optimization',
      description: 'AI ensures your posts meet LinkedIn requirements'
    },
    {
      icon: Users,
      title: 'Recruiter Focused',
      description: 'Built specifically for modern recruitment workflows'
    }
  ]

  const benefits = [
    'Save hours on job description writing',
    'Ensure consistent, professional quality',
    'Optimize for LinkedIn engagement',
    'Streamline your hiring process'
  ]

  return (
    <div className="min-h-screen">
      {/* Hero Section */}
      <section className="relative overflow-hidden bg-gradient-to-br from-primary-600 via-primary-700 to-indigo-800 text-white">
        <div className="absolute inset-0 bg-black/20"></div>
        <div className="relative max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-24 lg:py-32">
          <div className="text-center">
            <motion.div
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.6 }}
            >
              <h1 className="text-4xl md:text-6xl font-bold mb-6">
                AI Job Posting Agent
              </h1>
              <p className="text-xl md:text-2xl mb-8 text-primary-100 max-w-3xl mx-auto">
                Transform your recruitment process with AI-powered job descriptions 
                that automatically post to LinkedIn
              </p>
            </motion.div>
            
            <motion.div
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.6, delay: 0.2 }}
              className="flex flex-col sm:flex-row gap-4 justify-center items-center"
            >
              <Link href="/auth/register">
                <button className="btn-primary text-lg px-8 py-3 flex items-center gap-2 group">
                  Get Started Free
                  <ArrowRight className="w-5 h-5 group-hover:translate-x-1 transition-transform" />
                </button>
              </Link>
              <button 
                className="btn-secondary text-lg px-8 py-3 flex items-center gap-2 group"
                onClick={() => setIsPlaying(!isPlaying)}
              >
                <Play className="w-5 h-5" />
                Watch Demo
              </button>
            </motion.div>
          </div>
        </div>
        
        {/* Floating Elements */}
        <motion.div
          animate={{ y: [0, -20, 0] }}
          transition={{ duration: 4, repeat: Infinity }}
          className="absolute top-20 left-10 opacity-20"
        >
          <Rocket className="w-16 h-16 text-primary-200" />
        </motion.div>
        <motion.div
          animate={{ y: [0, 20, 0] }}
          transition={{ duration: 5, repeat: Infinity, delay: 1 }}
          className="absolute top-32 right-20 opacity-20"
        >
          <Brain className="w-12 h-12 text-indigo-200" />
        </motion.div>
      </section>

      {/* Features Section */}
      <section className="py-20 bg-white">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            whileInView={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.6 }}
            viewport={{ once: true }}
            className="text-center mb-16"
          >
            <h2 className="text-3xl md:text-4xl font-bold text-gray-900 mb-4">
              Why Choose AI Job Posting Agent?
            </h2>
            <p className="text-xl text-gray-600 max-w-2xl mx-auto">
              Streamline your recruitment process with cutting-edge AI technology
            </p>
          </motion.div>

          <div className="grid md:grid-cols-2 lg:grid-cols-4 gap-8">
            {features.map((feature, index) => (
              <motion.div
                key={feature.title}
                initial={{ opacity: 0, y: 20 }}
                whileInView={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.6, delay: index * 0.1 }}
                viewport={{ once: true }}
                className="card text-center group hover:shadow-xl transition-shadow duration-300"
              >
                <div className="w-16 h-16 bg-primary-100 rounded-full flex items-center justify-center mx-auto mb-4 group-hover:bg-primary-200 transition-colors">
                  <feature.icon className="w-8 h-8 text-primary-600" />
                </div>
                <h3 className="text-xl font-semibold text-gray-900 mb-2">
                  {feature.title}
                </h3>
                <p className="text-gray-600">
                  {feature.description}
                </p>
              </motion.div>
            ))}
          </div>
        </div>
      </section>

      {/* Benefits Section */}
      <section className="py-20 bg-gray-50">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="grid lg:grid-cols-2 gap-12 items-center">
            <motion.div
              initial={{ opacity: 0, x: -20 }}
              whileInView={{ opacity: 1, x: 0 }}
              transition={{ duration: 0.6 }}
              viewport={{ once: true }}
            >
              <h2 className="text-3xl md:text-4xl font-bold text-gray-900 mb-6">
                Transform Your Hiring Process
              </h2>
              <p className="text-lg text-gray-600 mb-8">
                Stop spending hours writing job descriptions. Our AI creates 
                professional, engaging content that attracts top talent while 
                you focus on what matters most.
              </p>
              
              <div className="space-y-4">
                {benefits.map((benefit, index) => (
                  <motion.div
                    key={benefit}
                    initial={{ opacity: 0, x: -20 }}
                    whileInView={{ opacity: 1, x: 0 }}
                    transition={{ duration: 0.6, delay: index * 0.1 }}
                    viewport={{ once: true }}
                    className="flex items-center gap-3"
                  >
                    <CheckCircle className="w-5 h-5 text-green-500 flex-shrink-0" />
                    <span className="text-gray-700">{benefit}</span>
                  </motion.div>
                ))}
              </div>
            </motion.div>

            <motion.div
              initial={{ opacity: 0, x: 20 }}
              whileInView={{ opacity: 1, x: 0 }}
              transition={{ duration: 0.6 }}
              viewport={{ once: true }}
              className="relative"
            >
              <div className="card bg-gradient-to-br from-primary-50 to-indigo-50 border-primary-200">
                <div className="text-center">
                  <div className="w-20 h-20 bg-primary-100 rounded-full flex items-center justify-center mx-auto mb-6">
                    <Rocket className="w-10 h-10 text-primary-600" />
                  </div>
                  <h3 className="text-2xl font-bold text-gray-900 mb-4">
                    Ready to Get Started?
                  </h3>
                  <p className="text-gray-600 mb-6">
                    Join thousands of recruiters who are already saving time 
                    and improving their hiring results.
                  </p>
                  <Link href="/auth/register">
                    <button className="btn-primary w-full">
                      Start Creating Jobs
                    </button>
                  </Link>
                </div>
              </div>
            </motion.div>
          </div>
        </div>
      </section>

      {/* CTA Section */}
      <section className="py-20 bg-primary-600 text-white">
        <div className="max-w-4xl mx-auto text-center px-4 sm:px-6 lg:px-8">
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            whileInView={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.6 }}
            viewport={{ once: true }}
          >
            <h2 className="text-3xl md:text-4xl font-bold mb-6">
              Ready to Revolutionize Your Recruitment?
            </h2>
            <p className="text-xl text-primary-100 mb-8">
              Join the future of hiring with AI-powered job descriptions
            </p>
            <div className="flex flex-col sm:flex-row gap-4 justify-center">
              <Link href="/auth/register">
                <button className="btn-primary bg-white text-primary-600 hover:bg-gray-100">
                  Get Started Free
                </button>
              </Link>
              <Link href="/auth/login">
                <button className="btn-secondary border-white text-white hover:bg-white hover:text-primary-600">
                  Sign In
                </button>
              </Link>
            </div>
          </motion.div>
        </div>
      </section>
    </div>
  )
}
