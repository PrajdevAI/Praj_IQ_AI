import React from 'react'
import { SignIn } from '@clerk/clerk-react'

export default function SignInPage(){
  return (
    <div style={{maxWidth: '400px', margin: '4rem auto'}}>
      <SignIn 
        routing="path" 
        path="/sign-in"
        redirectUrl="/dashboard"
        signUpUrl="/sign-up"
      />
    </div>
  )
}
