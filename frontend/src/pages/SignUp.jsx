import React from 'react'
import { SignUp } from '@clerk/clerk-react'

export default function SignUpPage(){
  return (
    <div style={{maxWidth: '400px', margin: '4rem auto'}}>
      <SignUp 
        routing="path" 
        path="/sign-up"
        redirectUrl="/dashboard"
        signInUrl="/sign-in"
      />
    </div>
  )
}
