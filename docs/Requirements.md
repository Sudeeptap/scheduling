ChatBot Requirements [Doctor’s Assistant]

To implement “Doctor’s Assistant” - a chatbot that can answer queries posted in natural language regarding doctor’s availability. 

The Chatbot has to be implemented using 
Responses API
Tool Calling with Responses API

The bot can be implemented either in Python or Java. Refer to OpenAI Documentation at https://developers.openai.com/api/docs

Detailed requirements are listed below:

The list of doctors, their specialty/department and their availability (dates/days and timings) to be configured in a database .
The bot should support (but not limited to) the following types of conversations:
	(i)	
Agent : Hello and welcome to the Super Clinic
Caller1: Hi can I have an appointment with Dr X
Agent: Sure, what date and time would you like the appointment
Caller1 : I would like to meet him tomorrow at 10 AM
Agent: Sorry, he is not available at 10 AM, are you available at 11 AM
Caller1: Ok
Agent Great, call is booked
	
	(ii)	
Agent : Hello and welcome to the Super Clinic
Caller2: Hi, I have been having these rashes for the past few days. Would like to meet a doctor, could you help
Agent: You would have to see a dermatologist for this problem. Sorry, we do not have any doctors with that speciality at our clinic. Is there anything else that I could help you with?
Caller2: No
Agent:  Thank you for contacting Super Clinic. Have a good day!

	(iii)	
Agent : Hello and welcome to the Super Clinic
Caller3: Hi, I fell down while playing badminton - my ankle is swollen. Would like to meet a doctor today, could you help
Agent: Sure, which of the following orthopedic doctor(s) would you like to meet? <lists all the specialists>
Caller3: I would like to meet Dr.X
Agent:  He is not available today, do you want to meet him tomorrow at 10:30 AM
Caller3 : oh! in that case can I meet Dr.Y today
Agent: Sure, he is available at 11:00 AM. Is that fine?
Caller2: Ok
Agent Great, call is booked

Whenever an appointment is booked, the database to be modified to indicate the unavailability of the doctor for that slot [for future bookings]. The details of the patient may be collected and stored for reference.
