'use client'

import { useState, useEffect } from 'react'
import { motion } from 'framer-motion'
import { 
  Plus, 
  Briefcase, 
  Linkedin, 
  Settings, 
  LogOut,
  User,
  TrendingUp,
  Clock
} from 'lucide-react'
import Link from 'next/link'
import { useRouter } from 'next/navigation'
import toast from 'react-hot-toast'
import JobPostForm from '@/components/JobPostForm'
import JobPostCard from '@/components/JobPostCard'

interface JobPost {
  id: number
  role_request: string
  requirements?: string
  jd_draft?: string
  final_jd?: string
  status: string
  linkedin_post_id?: string
  linkedin_post_url?: string
  google_form_link?: string
  created_at: string
  updated_at?: string
}

interface User {
  id: number
  email: string
  username: string
  full_name?: string
  company?: string
}

export default function DashboardPage() {
  const [user, setUser] = useState<User | null>(null)
  const [jobPosts, setJobPosts] = useState<JobPost[]>([])
  const [showJobForm, setShowJobForm] = useState(false)
  const [isLoading, setIsLoading] = useState(true)
  const router = useRouter()

  useEffect(() => {
    const token = localStorage.getItem('token')
    if (!token) {
      router.push('/auth/login')
      return
    }

    fetchUserData()
    fetchJobPosts()
  }, [router])

  const fetchUserData = async () => {
    try {
      const token = localStorage.getItem('token')
      const response = await fetch('/api/auth/me', {
        headers: {
          'Authorization': `Bearer ${token}`
        }
      })

      if (response.ok) {
        const userData = await response.json()
        setUser(userData)
      } else {
        localStorage.removeItem('token')
        router.push('/auth/login')
      }
    } catch (error) {
      console.error('Error fetching user data:', error)
    }
  }

  const fetchJobPosts = async () => {
    try {
      const token = localStorage.getItem('token')
      const response = await fetch('/api/jobs/', {
        headers: {
          'Authorization': `Bearer ${token}`
        }
      })

      if (response.ok) {
        const data = await response.json()
        setJobPosts(data)
      }
    } catch (error) {
      console.error('Error fetching job posts:', error)
    } finally {
      setIsLoading(false)
    }
  }

  const handleLogout = () => {
    localStorage.removeItem('token')
    router.push('/')
    toast.success('Logged out successfully')
  }

  const handleJobCreated = (newJob: JobPost) => {
    setJobPosts(prev => [newJob, ...prev])
    setShowJobForm(false)
    toast.success('Job post created successfully!')
  }

  const handleJobUpdated = (updatedJob: JobPost) => {
    setJobPosts(prev => prev.map(job => 
      job.id === updatedJob.id ? updatedJob : job
    ))
    toast.success('Job post updated successfully!')
  }

  const handleJobDeleted = (jobId: number) => {
    setJobPosts(prev => prev.filter(job => job.id !== jobId))
    toast.success('Job post deleted successfully!')
  }

  const getStatusColor = (status: string) => {
    switch (status) {
      case 'DRAFT': return 'bg-yellow-100 text-yellow-800'
      case 'DRAFTED': return 'bg-blue-100 text-blue-800'
      case 'APPROVED': return 'bg-green-100 text-green-800'
      case 'POSTED': return 'bg-purple-100 text-purple-800'
      default: return 'bg-gray-100 text-gray-800'
    }
  }

  const getStatusIcon = (status: string) => {
    switch (status) {
      case 'DRAFT': return <Clock className="w-4 h-4" />
      case 'DRAFTED': return <Briefcase className="w-4 h-4" />
      case 'APPROVED': return <TrendingUp className="w-4 h-4" />
      case 'POSTED': return <Linkedin className="w-4 h-4" />
      default: return <Clock className="w-4 h-4" />
    }
  }

  if (isLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <div className="animate-spin rounded-full h-32 w-32 border-b-2 border-primary-600"></div>
      </div>
    )
  }

  return (
    <div className="min-h-screen bg-gray-50">
      {/* Header */}
      <header className="bg-white shadow-sm border-b border-gray-200">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="flex justify-between items-center py-4">
            <div className="flex items-center space-x-4">
              <h1 className="text-2xl font-bold text-gray-900">
                AI Job Posting Agent
              </h1>
            </div>
            
            <div className="flex items-center space-x-4">
              <div className="flex items-center space-x-2">
                <User className="w-5 h-5 text-gray-500" />
                <span className="text-sm text-gray-700">
                  {user?.full_name || user?.username}
                </span>
              </div>
              
              <button
                onClick={handleLogout}
                className="flex items-center space-x-2 text-gray-500 hover:text-gray-700 transition-colors"
              >
                <LogOut className="w-5 h-5" />
                <span className="text-sm">Logout</span>
              </button>
            </div>
          </div>
        </div>
      </header>

      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        {/* Stats Cards */}
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.6 }}
          className="grid grid-cols-1 md:grid-cols-4 gap-6 mb-8"
        >
          <div className="card text-center">
            <div className="text-2xl font-bold text-primary-600">{jobPosts.length}</div>
            <div className="text-sm text-gray-600">Total Jobs</div>
          </div>
          
          <div className="card text-center">
            <div className="text-2xl font-bold text-yellow-600">
              {jobPosts.filter(job => job.status === 'DRAFT' || job.status === 'DRAFTED').length}
            </div>
            <div className="text-sm text-gray-600">In Progress</div>
          </div>
          
          <div className="card text-center">
            <div className="text-2xl font-bold text-green-600">
              {jobPosts.filter(job => job.status === 'APPROVED').length}
            </div>
            <div className="text-sm text-gray-600">Approved</div>
          </div>
          
          <div className="card text-center">
            <div className="text-2xl font-bold text-purple-600">
              {jobPosts.filter(job => job.status === 'POSTED').length}
            </div>
            <div className="text-sm text-gray-600">Posted to LinkedIn</div>
          </div>
        </motion.div>

        {/* Create Job Button */}
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.6, delay: 0.1 }}
          className="mb-8"
        >
          <button
            onClick={() => setShowJobForm(true)}
            className="btn-primary flex items-center space-x-2"
          >
            <Plus className="w-5 h-5" />
            <span>Create New Job Post</span>
          </button>
        </motion.div>

        {/* Job Posts */}
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.6, delay: 0.2 }}
        >
          {jobPosts.length === 0 ? (
            <div className="card text-center py-12">
              <Briefcase className="w-16 h-16 text-gray-400 mx-auto mb-4" />
              <h3 className="text-xl font-semibold text-gray-900 mb-2">
                No job posts yet
              </h3>
              <p className="text-gray-600 mb-6">
                Create your first job post to get started with AI-powered recruitment
              </p>
              <button
                onClick={() => setShowJobForm(true)}
                className="btn-primary"
              >
                Create Your First Job Post
              </button>
            </div>
          ) : (
            <div className="grid gap-6">
              {jobPosts.map((job, index) => (
                <JobPostCard
                  key={job.id}
                  job={job}
                  onUpdate={handleJobUpdated}
                  onDelete={handleJobDeleted}
                  index={index}
                />
              ))}
            </div>
          )}
        </motion.div>
      </div>

      {/* Job Post Form Modal */}
      {showJobForm && (
        <JobPostForm
          onClose={() => setShowJobForm(false)}
          onJobCreated={handleJobCreated}
        />
      )}
    </div>
  )
}
