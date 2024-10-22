import frappe
import json
from frappe.utils import cint, today, get_url, now_datetime, getdate, cstr, get_datetime
from datetime import datetime, timedelta
import requests
import random
import string
import urllib.parse
from .glific_integration import create_contact, start_contact_flow, get_contact_by_phone
from .background_jobs import enqueue_glific_actions



def authenticate_api_key(api_key):
    try:
        # Check if the provided API key exists and is enabled
        api_key_doc = frappe.get_doc("API Key", {"key": api_key, "enabled": 1})
        return api_key_doc.name
    except frappe.DoesNotExistError:
        # Handle the case where the API key does not exist or is not enabled
        return None






@frappe.whitelist(allow_guest=True)
def list_districts():
    try:
        # Get the JSON data from the request body
        data = json.loads(frappe.request.data)
        api_key = data.get('api_key')
        state = data.get('state')

        if not api_key or not state:
            frappe.response.http_status_code = 400
            return {"status": "error", "message": "API key and state are required"}

        if not authenticate_api_key(api_key):
            frappe.response.http_status_code = 401
            return {"status": "error", "message": "Invalid API key"}

        districts = frappe.get_all(
            "District",
            filters={"state": state},
            fields=["name", "district_name"]
        )

        response_data = {district.name: district.district_name for district in districts}

        frappe.response.http_status_code = 200
        return {"status": "success", "data": response_data}

    except Exception as e:
        frappe.log_error(f"List Districts Error: {str(e)}")
        frappe.response.http_status_code = 500
        return {"status": "error", "message": str(e)}

@frappe.whitelist(allow_guest=True)
def list_cities():
    try:
        # Get the JSON data from the request body
        data = json.loads(frappe.request.data)
        api_key = data.get('api_key')
        district = data.get('district')

        if not api_key or not district:
            frappe.response.http_status_code = 400
            return {"status": "error", "message": "API key and district are required"}

        if not authenticate_api_key(api_key):
            frappe.response.http_status_code = 401
            return {"status": "error", "message": "Invalid API key"}

        cities = frappe.get_all(
            "City",
            filters={"district": district},
            fields=["name", "city_name"]
        )

        response_data = {city.name: city.city_name for city in cities}

        frappe.response.http_status_code = 200
        return {"status": "success", "data": response_data}

    except Exception as e:
        frappe.log_error(f"List Cities Error: {str(e)}")
        frappe.response.http_status_code = 500
        return {"status": "error", "message": str(e)}



def send_whatsapp_message(phone_number, message):
    # Fetch Gupshup OTP Settings
    gupshup_settings = frappe.get_single("Gupshup OTP Settings")

    if not gupshup_settings:
        frappe.log_error("Gupshup OTP Settings not found")
        return False

    if not all([gupshup_settings.api_key, gupshup_settings.source_number,
                gupshup_settings.app_name, gupshup_settings.api_endpoint]):
        frappe.log_error("Incomplete Gupshup OTP Settings")
        return False

    url = gupshup_settings.api_endpoint

    payload = {
        "channel": "whatsapp",
        "source": gupshup_settings.source_number,
        "destination": phone_number,
        "message": json.dumps({"type": "text", "text": message}),
        "src.name": gupshup_settings.app_name
    }

    headers = {
        "apikey": gupshup_settings.api_key,
        "Content-Type": "application/x-www-form-urlencoded",
        "Cache-Control": "no-cache"
    }

    try:
        response = requests.post(url, data=payload, headers=headers)
        response.raise_for_status()  # Raise an exception for non-200 status codes
        return True
    except requests.exceptions.RequestException as e:
        frappe.log_error(f"Error sending WhatsApp message: {str(e)}")
        return False






@frappe.whitelist(allow_guest=True)
def get_school_name_keyword_list(api_key, start=0, limit=10):
    # Verify the API key
    if not authenticate_api_key(api_key):
        frappe.throw("Invalid API key")

    start = cint(start)
    limit = cint(limit)

    # Query the school doctype to fetch the name1 and keyword fields
    schools = frappe.db.get_all("School",
                                fields=["name", "name1", "keyword"],
                                limit_start=start,
                                limit_page_length=limit)

    # Fixed WhatsApp number
    whatsapp_number = "918454812392"

    # Prepare the response data
    response_data = []
    for school in schools:
        # Prepend "tapschool:" to the keyword
        keyword_with_prefix = f"tapschool:{school.keyword}"

        # Create the WhatsApp link using the fixed number and keyword
        whatsapp_link = f"https://api.whatsapp.com/send?phone={whatsapp_number}&text={keyword_with_prefix}"

        school_data = {
            "school_name": school.name1,
            "teacher_keyword": keyword_with_prefix,
            "whatsapp_link": whatsapp_link
        }
        response_data.append(school_data)

    # Return the response as a JSON object
    return response_data



@frappe.whitelist(allow_guest=True)
def verify_keyword():
    # Parse the request data
    data = frappe.request.get_json()

    # Verify the API key
    if not data or 'api_key' not in data or not authenticate_api_key(data['api_key']):
        frappe.response.http_status_code = 401
        frappe.response.update({
            "status": "failure",
            "school_name": None,
            "model": None,
            "error": "Invalid API key"
        })
        return

    if 'keyword' not in data:
        frappe.response.http_status_code = 400
        frappe.response.update({
            "status": "failure",
            "school_name": None,
            "model": None,
            "error": "Keyword parameter is missing"
        })
        return

    keyword = data['keyword']

    # Check if the keyword exists in the School doctype and retrieve the smodel and name1 fields
    school = frappe.db.get_value("School", {"keyword": keyword}, ["name1", "model"], as_dict=True)

    if school:
        frappe.response.http_status_code = 200
        frappe.response.update({
            "status": "success",
            "school_name": school.name1,
            "model": school.model
        })
    else:
        frappe.response.http_status_code = 404
        frappe.response.update({
            "status": "failure",
            "school_name": None,
            "model": None
        })



@frappe.whitelist(allow_guest=True)
def create_teacher(api_key, keyword, first_name, phone_number, glific_id, last_name=None, email=None, language=None):
    try:
        # Verify the API key
        if not authenticate_api_key(api_key):
            frappe.throw("Invalid API key")

        # Find the school based on the provided keyword
        school = frappe.db.get_value("School", {"keyword": keyword}, "name")
        if not school:
            return {
                "error": f"No school found with the keyword: {keyword}"
            }

        # Create a new teacher document
        teacher = frappe.new_doc("Teacher")
        teacher.first_name = first_name
        teacher.school = school
        teacher.phone_number = phone_number
        teacher.glific_id = glific_id  # Set the glific_id field (mandatory)

        # Set the optional fields if provided
        if last_name:
            teacher.last_name = last_name
        if email:
            teacher.email = email
        if language:
            teacher.language = language

        # Insert the teacher document
        teacher.insert(ignore_permissions=True)

        # Commit the changes
        frappe.db.commit()

        return {
            "message": "Teacher created successfully",
            "teacher_id": teacher.name
        }
    except frappe.DuplicateEntryError:
        return {
            "error": "Teacher with the same phone number already exists"
        }
    except Exception as e:
        return {
            "error": f"An error occurred while creating teacher: {str(e)}"
        }







@frappe.whitelist(allow_guest=True)
def list_batch_keyword(api_key):
    if not authenticate_api_key(api_key):
        frappe.throw("Invalid API key")

    current_date = getdate(today())
    whatsapp_number = "918454812392"
    response_data = []

    # Get all batch onboarding entries
    batch_onboarding_list = frappe.get_all(
        "Batch onboarding",
        fields=["batch", "school", "batch_skeyword"]
    )

    for onboarding in batch_onboarding_list:
        batch = frappe.get_doc("Batch", onboarding.batch)
        
        # Check if the batch is active and registration end date is in the future
        if batch.active and getdate(batch.regist_end_date) >= current_date:
            school_name = frappe.get_value("School", onboarding.school, "name1")
            keyword_with_prefix = f"tapschool:{onboarding.batch_skeyword}"
            batch_reg_link = f"https://api.whatsapp.com/send?phone={whatsapp_number}&text={keyword_with_prefix}"

            response_data.append({
                "School_name": school_name,
                "batch_keyword": onboarding.batch_skeyword,
                "batch_id": batch.batch_id,
                "Batch_regLink": batch_reg_link
            })

    return response_data





@frappe.whitelist(allow_guest=True)
def create_student():
    try:
        # Get the data from the request
        api_key = frappe.form_dict.get('api_key')
        student_name = frappe.form_dict.get('student_name')
        phone = frappe.form_dict.get('phone')
        gender = frappe.form_dict.get('gender')
        grade = frappe.form_dict.get('grade')
        language_name = frappe.form_dict.get('language')
        batch_skeyword = frappe.form_dict.get('batch_skeyword')
        vertical = frappe.form_dict.get('vertical')
        glific_id = frappe.form_dict.get('glific_id')

        if not authenticate_api_key(api_key):
            frappe.response.status_code = 202
            return {"status": "error", "message": "Invalid API key"}

        # Validate required fields
        if not all([student_name, phone, gender, grade, language_name, batch_skeyword, vertical, glific_id]):
            frappe.response.status_code = 202
            return {"status": "error", "message": "All fields are required"}

        # Get the school and batch from batch_skeyword
        batch_onboarding = frappe.get_all(
            "Batch onboarding",
            filters={"batch_skeyword": batch_skeyword},
            fields=["name", "school", "batch", "kit_less"]
        )

        if not batch_onboarding:
            frappe.response.status_code = 202
            return {"status": "error", "message": "Invalid batch_skeyword"}

        school_id = batch_onboarding[0].school
        batch = batch_onboarding[0].batch
        kitless = batch_onboarding[0].kit_less

        # Check if the batch is active and registration end date is not passed
        batch_doc = frappe.get_doc("Batch", batch)
        current_date = getdate()

        if not batch_doc.active:
            frappe.response.status_code = 202
            return {"status": "error", "message": "The batch is not active"}

        if batch_doc.regist_end_date:
            try:
                regist_end_date = getdate(cstr(batch_doc.regist_end_date))
                if regist_end_date < current_date:
                    frappe.response.status_code = 202
                    return {"status": "error", "message": "Registration for this batch has ended"}
            except Exception as e:
                frappe.log_error(f"Error parsing registration end date: {str(e)}")
                frappe.response.status_code = 202
                return {"status": "error", "message": "Invalid registration end date format"}

        # Get the course vertical using the label
        course_vertical = frappe.get_all(
            "Course Verticals",
            filters={"name2": vertical},
            fields=["name"]
        )

        if not course_vertical:
            frappe.response.status_code = 202
            return {"status": "error", "message": "Invalid vertical label"}

        # Check if student with glific_id already exists
        existing_student = frappe.get_all(
            "Student",
            filters={"glific_id": glific_id},
            fields=["name", "name1", "phone"]
        )

        if existing_student:
            student = frappe.get_doc("Student", existing_student[0].name)
            
            # Check if name and phone match
            if student.name1 == student_name and student.phone == phone:
                # Update existing student
                student.grade = grade
                student.language = get_tap_language(language_name)
                student.school_id = school_id
                student.save(ignore_permissions=True)
            else:
                # Create new student
                student = create_new_student(student_name, phone, gender, school_id, grade, language_name, glific_id)
        else:
            # Create new student
            student = create_new_student(student_name, phone, gender, school_id, grade, language_name, glific_id)

        # Get the appropriate course level based on the kitless option
        course_level = get_course_level(course_vertical[0].name, grade, kitless)

        # Adding the enrollment details to the student
        student.append("enrollment", {
            "batch": batch,
            "course": course_level,
            "grade": grade,
            "date_joining": now_datetime().date(),
            "school": school_id
        })

        student.save(ignore_permissions=True)

        return {
            "status": "success",
            "crm_student_id": student.name
        }

    except frappe.ValidationError as e:
        frappe.log_error(f"Student Creation Validation Error: {str(e)}")
        frappe.response.status_code = 202
        return {"status": "error", "message": str(e)}
    except Exception as e:
        frappe.log_error(f"Student Creation Error: {str(e)}")
        frappe.response.status_code = 202
        return {"status": "error", "message": str(e)}







def create_new_student(student_name, phone, gender, school_id, grade, language_name, glific_id):
    student = frappe.get_doc({
        "doctype": "Student",
        "name1": student_name,
        "phone": phone,
        "gender": gender,
        "school_id": school_id,
        "grade": grade,
        "language": get_tap_language(language_name),
        "glific_id": glific_id,
        "joined_on": now_datetime().date(),
        "status": "active"
    })

    student.insert(ignore_permissions=True)
    return student

def get_tap_language(language_name):
    tap_language = frappe.get_all(
        "TAP Language",
        filters={"language_name": language_name},
        fields=["name"]
    )

    if not tap_language:
        frappe.throw(f"No TAP Language found for language name: {language_name}")

    return tap_language[0].name





@frappe.whitelist(allow_guest=True)
def verify_batch_keyword():
    try:
        # Get the JSON data from the request body
        data = json.loads(frappe.request.data)
        api_key = data.get('api_key')
        batch_skeyword = data.get('batch_skeyword')

        if not api_key or not batch_skeyword:
            frappe.response.http_status_code = 400
            return {"status": "error", "message": "API key and batch_skeyword are required"}

        if not authenticate_api_key(api_key):
            frappe.response.http_status_code = 401
            return {"status": "error", "message": "Invalid API key"}

        batch_onboarding = frappe.get_all(
            "Batch onboarding",
            filters={"batch_skeyword": batch_skeyword},
            fields=["school", "batch", "model","kit_less"]
        )

        if not batch_onboarding:
            frappe.response.http_status_code = 202
            return {"status": "error", "message": "Invalid batch keyword"}

        batch_id = batch_onboarding[0].batch
        batch_doc = frappe.get_doc("Batch", batch_id)
        current_date = getdate()

        if not batch_doc.active:
            frappe.response.http_status_code = 202
            return {"status": "error", "message": "The batch is not active"}

        if batch_doc.regist_end_date:
            try:
                regist_end_date = getdate(cstr(batch_doc.regist_end_date))
                if regist_end_date < current_date:
                    frappe.response.http_status_code = 202
                    return {"status": "error", "message": "Registration for this batch has ended"}
            except Exception as e:
                frappe.log_error(f"Error parsing registration end date: {str(e)}")
                frappe.response.http_status_code = 500
                return {"status": "error", "message": "Invalid registration end date format"}

        school_name = cstr(frappe.get_value("School", batch_onboarding[0].school, "name1"))
        batch_id = cstr(frappe.get_value("Batch", batch_onboarding[0].batch, "batch_id"))
        tap_model = frappe.get_doc("Tap Models", batch_onboarding[0].model)
        kit_less = batch_onboarding[0].kit_less

        response = {
            "school_name": school_name,
            "batch_id": batch_id,
            "tap_model_id": cstr(tap_model.name),
            "tap_model_name": cstr(tap_model.mname),
            "kit_less": kit_less,
            "status": "success"
        }

        frappe.response.http_status_code = 200
        return response

    except Exception as e:
        frappe.log_error(f"Verify Batch Keyword Error: {str(e)}")
        frappe.response.http_status_code = 500
        return {"status": "error", "message": str(e)}


@frappe.whitelist(allow_guest=True)
def grade_list(api_key, keyword):
    if not authenticate_api_key(api_key):
        frappe.throw("Invalid API key")

    # Find the batch onboarding document based on the batch_skeyword
    batch_onboarding = frappe.get_all(
        "Batch onboarding",
        filters={"batch_skeyword": keyword},
        fields=["name", "from_grade", "to_grade"]
    )

    if not batch_onboarding:
        frappe.throw("No batch found with the provided keyword")

    # Extract the from_grade and to_grade from the batch onboarding document
    from_grade = cint(batch_onboarding[0].from_grade)
    to_grade = cint(batch_onboarding[0].to_grade)

    # Generate a dictionary of grades based on the from_grade and to_grade
    grades = {}
    count = 0
    for i, grade in enumerate(range(from_grade, to_grade + 1), start=1):
        grades[str(i)] = str(grade)
        count += 1

    # Add the count to the grades dictionary
    grades["count"] = str(count)

    return grades


@frappe.whitelist(allow_guest=True)
def course_vertical_list():
    try:
        # Get JSON data from the request
        data = frappe.local.form_dict
        api_key = data.get('api_key')
        keyword = data.get('keyword')

        if not authenticate_api_key(api_key):
            frappe.throw("Invalid API key")

        batch_onboarding = frappe.get_all(
            "Batch onboarding",
            filters={"batch_skeyword": keyword},
            fields=["name"]
        )

        if not batch_onboarding:
            return {"error": "Invalid batch keyword"}

        batch_school_verticals = frappe.get_all(
            "Batch School Verticals",
            filters={"parent": batch_onboarding[0].name},
            fields=["course_vertical"]
        )

        response_data = {}
        for vertical in batch_school_verticals:
            course_vertical = frappe.get_doc("Course Verticals", vertical.course_vertical)
            response_data[course_vertical.vertical_id] = course_vertical.name2

        return response_data

    except Exception as e:
        frappe.log_error(f"Course Vertical List Error: {str(e)}")
        return {"status": "error", "message": str(e)}



@frappe.whitelist(allow_guest=True)
def list_schools():
    # Parse the request data
    data = frappe.request.get_json()

    # Verify the API key
    if not data or 'api_key' not in data or not authenticate_api_key(data['api_key']):
        frappe.response.http_status_code = 401
        frappe.response.update({
            "status": "failure",
            "schools": [],
            "error": "Invalid API key"
        })
        return

    district = data.get('district')
    city = data.get('city')

    filters = {}
    if district:
        filters['district'] = district
    if city:
        filters['city'] = city

    # Fetch schools based on filters
    schools = frappe.get_all("School", filters=filters, fields=["name1 as School_name"])

    if schools:
        frappe.response.http_status_code = 200
        frappe.response.update({
            "status": "success",
            "schools": schools
        })
    else:
        frappe.response.http_status_code = 404
        frappe.response.update({
            "status": "failure",
            "schools": [],
            "message": "No schools found for the given criteria"
        })



@frappe.whitelist(allow_guest=True)
def course_vertical_list_count():
    try:
        # Get JSON data from the request
        data = frappe.local.form_dict
        api_key = data.get('api_key')
        keyword = data.get('keyword')

        if not authenticate_api_key(api_key):
            frappe.throw("Invalid API key")

        batch_onboarding = frappe.get_all(
            "Batch onboarding",
            filters={"batch_skeyword": keyword},
            fields=["name"]
        )

        if not batch_onboarding:
            return {"error": "Invalid batch keyword"}

        batch_school_verticals = frappe.get_all(
            "Batch School Verticals",
            filters={"parent": batch_onboarding[0].name},
            fields=["course_vertical"]
        )

        response_data = {}
        count = 0

        for index, vertical in enumerate(batch_school_verticals, start=1):
            course_vertical = frappe.get_doc("Course Verticals", vertical.course_vertical)
            response_data[str(index)] = course_vertical.name2
            count += 1

        response_data["count"] = str(count)

        return response_data

    except Exception as e:
        frappe.log_error(f"Course Vertical List Count Error: {str(e)}")
        return {"status": "error", "message": str(e)}






@frappe.whitelist(allow_guest=True)
def send_otp_gs():
    data = frappe.request.get_json()
    
    if not data or 'api_key' not in data or not authenticate_api_key(data['api_key']):
        frappe.response.http_status_code = 401
        return {"status": "failure", "message": "Invalid API key"}
    
    if 'phone' not in data:
        frappe.response.http_status_code = 400
        return {"status": "failure", "message": "Phone number is required"}
    
    phone_number = data['phone']

    # Check if the phone number is already registered
    existing_teacher = frappe.get_all("Teacher", filters={"phone_number": phone_number}, fields=["name"])
    if existing_teacher:
        frappe.response.http_status_code = 409
        return {
            "status": "failure",
            "message": "A teacher with this phone number already exists",
            "existing_teacher_id": existing_teacher[0].name
        }

    otp = ''.join(random.choices(string.digits, k=4))
    
    # Store OTP in the database (you might want to create a new doctype for this)
    frappe.get_doc({
        "doctype": "OTP Verification",
        "phone_number": phone_number,
        "otp": otp,
        "expiry": now_datetime() + timedelta(minutes=15)
    }).insert(ignore_permissions=True)
    
    message = f"{otp} is your verification code"
    if send_whatsapp_message(phone_number, message):
        frappe.response.http_status_code = 200
        return {"status": "success", "message": "OTP sent successfully"}
    else:
        frappe.response.http_status_code = 500
        return {"status": "failure", "message": "Failed to send OTP"}







@frappe.whitelist(allow_guest=True)
def send_otp_v0():
    data = frappe.request.get_json()

    if not data or 'api_key' not in data or not authenticate_api_key(data['api_key']):
        frappe.response.http_status_code = 401
        return {"status": "failure", "message": "Invalid API key"}

    if 'phone' not in data:
        frappe.response.http_status_code = 400
        return {"status": "failure", "message": "Phone number is required"}

    phone_number = data['phone']

    # Check if the phone number is already registered
    existing_teacher = frappe.get_all("Teacher", filters={"phone_number": phone_number}, fields=["name"])
    if existing_teacher:
        frappe.response.http_status_code = 409
        return {
            "status": "failure",
            "message": "A teacher with this phone number already exists",
            "existing_teacher_id": existing_teacher[0].name
        }

    otp = ''.join(random.choices(string.digits, k=4))

    # Store OTP in the database
    frappe.get_doc({
        "doctype": "OTP Verification",
        "phone_number": phone_number,
        "otp": otp,
        "expiry": now_datetime() + timedelta(minutes=15)
    }).insert(ignore_permissions=True)

    # Send WhatsApp message using the API
    whatsapp_api_key = "J3tuS4rCqzcLiqt2SjyeiqYxjVLICnWb"  # Replace with your actual API key
    instance = "27715370"  # Replace with your actual instance ID
    message = f"Your OTP is: {otp}"
    
    api_url = f"https://chatspaz.com/api/v1/send/wa/message?api_key={whatsapp_api_key}&instance={instance}&to={phone_number}&type=text&message={message}"

    try:
        response = requests.get(api_url)
        response_data = response.json()

        if response_data.get("status") == "success":
            frappe.response.http_status_code = 200
            return {
                "status": "success",
                "message": "OTP sent successfully via WhatsApp",
                "whatsapp_message_id": response_data.get("id")
            }
        else:
            frappe.response.http_status_code = 500
            return {
                "status": "failure",
                "message": "Failed to send OTP via WhatsApp",
                "error": response_data.get("message")
            }

    except requests.RequestException as e:
        frappe.response.http_status_code = 500
        return {
            "status": "failure",
            "message": "Error occurred while sending OTP via WhatsApp",
            "error": str(e)
        }


@frappe.whitelist(allow_guest=True)
def send_otp():
    try:
        data = frappe.request.get_json()

        if not data or 'api_key' not in data or not authenticate_api_key(data['api_key']):
            frappe.response.http_status_code = 401
            return {"status": "failure", "message": "Invalid API key"}

        if 'phone' not in data:
            frappe.response.http_status_code = 400
            return {"status": "failure", "message": "Phone number is required"}

        phone_number = data['phone']

        # Check if the phone number is already registered
        existing_teacher = frappe.get_all("Teacher", filters={"phone_number": phone_number}, fields=["name"])
        if existing_teacher:
            frappe.response.http_status_code = 409
            return {
                "status": "failure",
                "message": "A teacher with this phone number already exists",
                "existing_teacher_id": existing_teacher[0].name
            }

        otp = ''.join(random.choices(string.digits, k=4))

        # Store OTP in the database
        try:
            otp_doc = frappe.get_doc({
                "doctype": "OTP Verification",
                "phone_number": phone_number,
                "otp": otp,
                "expiry": now_datetime() + timedelta(minutes=15)
            })
            otp_doc.insert(ignore_permissions=True)
            frappe.db.commit()
        except Exception as e:
            frappe.log_error(f"Failed to store OTP: {str(e)}", "OTP Storage Error")
            frappe.response.http_status_code = 500
            return {
                "status": "failure",
                "message": "Failed to store OTP in the database",
                "error": str(e)
            }

        # Send WhatsApp message using the API
        whatsapp_api_key = "J3tuS4rCqzcLiqt2SjyeiqYxjVLICnWb"  # Replace with your actual API key
        instance = "27715370"  # Replace with your actual instance ID
        message = f"Your OTP is: {otp}"
        
        api_url = f"https://chatspaz.com/api/v1/send/wa/message?api_key={whatsapp_api_key}&instance={instance}&to={phone_number}&type=text&message={message}"

        try:
            response = requests.get(api_url)
            response_data = response.json()

            if response_data.get("status") == "success":
                frappe.response.http_status_code = 200
                return {
                    "status": "success",
                    "message": "OTP sent successfully via WhatsApp",
                    "whatsapp_message_id": response_data.get("id")
                }
            else:
                frappe.log_error(f"WhatsApp API Error: {response_data.get('message')}", "WhatsApp API Error")
                frappe.response.http_status_code = 500
                return {
                    "status": "failure",
                    "message": "Failed to send OTP via WhatsApp",
                    "error": response_data.get("message")
                }

        except requests.RequestException as e:
            frappe.log_error(f"WhatsApp API Request Error: {str(e)}", "WhatsApp API Request Error")
            frappe.response.http_status_code = 500
            return {
                "status": "failure",
                "message": "Error occurred while sending OTP via WhatsApp",
                "error": str(e)
            }

    except Exception as e:
        frappe.log_error(f"Unexpected error in send_otp: {str(e)}", "Send OTP Error")
        frappe.response.http_status_code = 500
        return {
            "status": "failure",
            "message": "An unexpected error occurred",
            "error": str(e)
        }


@frappe.whitelist(allow_guest=True)
def send_otp_mock():
    data = frappe.request.get_json()

    if not data or 'api_key' not in data or not authenticate_api_key(data['api_key']):
        frappe.response.http_status_code = 401
        return {"status": "failure", "message": "Invalid API key"}

    if 'phone' not in data:
        frappe.response.http_status_code = 400
        return {"status": "failure", "message": "Phone number is required"}

    phone_number = data['phone']

    # Check if the phone number is already registered
    existing_teacher = frappe.get_all("Teacher", filters={"phone_number": phone_number}, fields=["name"])
    if existing_teacher:
        frappe.response.http_status_code = 409
        return {
            "status": "failure",
            "message": "A teacher with this phone number already exists",
            "existing_teacher_id": existing_teacher[0].name
        }

    otp = ''.join(random.choices(string.digits, k=4))

    # Store OTP in the database (you might want to create a new doctype for this)
    frappe.get_doc({
        "doctype": "OTP Verification",
        "phone_number": phone_number,
        "otp": otp,
        "expiry": now_datetime() + timedelta(minutes=15)
    }).insert(ignore_permissions=True)

    # Mock sending WhatsApp message by printing to console
    print(f"MOCK WHATSAPP MESSAGE: OTP {otp} sent to {phone_number}")

    frappe.response.http_status_code = 200
    return {
        "status": "success", 
        "message": "OTP sent successfully",
        "mock_otp": otp  # Include OTP in the response for testing
    }




@frappe.whitelist(allow_guest=True)
def verify_otp():
    try:
        data = frappe.request.get_json()

        if not data or 'api_key' not in data or not authenticate_api_key(data['api_key']):
            frappe.response.http_status_code = 401
            return {"status": "failure", "message": "Invalid API key"}

        if 'phone' not in data or 'otp' not in data:
            frappe.response.http_status_code = 400
            return {"status": "failure", "message": "Phone number and OTP are required"}

        phone_number = data['phone']
        otp = data['otp']

        # Use a direct SQL query to bypass permission checks
        verification = frappe.db.sql("""
            SELECT name, expiry
            FROM `tabOTP Verification`
            WHERE phone_number = %s AND otp = %s
            ORDER BY creation DESC
            LIMIT 1
        """, (phone_number, otp), as_dict=1)

        if not verification:
            frappe.response.http_status_code = 400
            return {"status": "failure", "message": "Invalid OTP"}

        verification = verification[0]

        # Convert expiry to datetime and compare with current datetime
        if get_datetime(verification.expiry) < now_datetime():
            frappe.response.http_status_code = 400
            return {"status": "failure", "message": "OTP has expired"}

        # Mark the phone number as verified using raw SQL
        frappe.db.sql("""
            UPDATE `tabOTP Verification`
            SET verified = 1
            WHERE name = %s
        """, (verification.name,))
        frappe.db.commit()

        frappe.response.http_status_code = 200
        return {"status": "success", "message": "Phone number verified successfully"}
    except Exception as e:
        frappe.log_error(f"OTP Verification Error: {str(e)}")
        frappe.response.http_status_code = 500
        return {"status": "failure", "message": "An error occurred during OTP verification"}







@frappe.whitelist(allow_guest=True)
def create_teacher_web():
    try:
        frappe.flags.ignore_permissions = True
        data = frappe.request.get_json()

        # Validate API key
        if 'api_key' not in data or not authenticate_api_key(data['api_key']):
            return {"status": "failure", "message": "Invalid API key"}

        # Validate required fields
        required_fields = ['firstName', 'phone', 'School_name', 'batch_name']
        for field in required_fields:
            if field not in data:
                return {"status": "failure", "message": f"Missing required field: {field}"}

        # Check if the phone number is verified
        verification = frappe.db.get_value("OTP Verification",
            {"phone_number": data['phone'], "verified": 1}, "name")
        if not verification:
            return {"status": "failure", "message": "Phone number is not verified. Please verify your phone number first."}

        # Check if the phone number already exists in Frappe
        existing_teacher = frappe.db.get_value("Teacher", {"phone_number": data['phone']}, "name")
        if existing_teacher:
            return {
                "status": "failure",
                "message": "A teacher with this phone number already exists",
                "existing_teacher_id": existing_teacher
            }

        # Get the school_id based on the School_name
        school = frappe.db.get_value("School", {"name1": data['School_name']}, "name")
        if not school:
            return {"status": "failure", "message": "School not found"}

        # Get the appropriate model for the school
        model_name = get_model_for_school(school)

        # Create new Teacher document
        new_teacher = frappe.get_doc({
            "doctype": "Teacher",
            "first_name": data['firstName'],
            "last_name": data.get('lastName', ''),
            "phone_number": data['phone'],
            "language": data.get('language', ''),
            "school_id": school,
            "batch_name":data['batch_name'] 
        })

        new_teacher.insert(ignore_permissions=True)

        # Get the school name
        school_name = frappe.db.get_value("School", school, "name1")

        # Get the language ID from TAP Language
        language_id = frappe.db.get_value("TAP Language", data.get('language'), "glific_language_id")
        if not language_id:
            language_id = frappe.db.get_value("TAP Language", {"language_name": "English"}, "glific_language_id")  # Default to English if not found

        # Try to create contact in Glific
        glific_contact = create_contact(
            data['firstName'],
            data['phone'],
            school_name,
            model_name,
            language_id,
            data['batch_name'] 
        )

        # If creation fails, try to get existing contact
        if not glific_contact or 'id' not in glific_contact:
            glific_contact = get_contact_by_phone(data['phone'])

        if glific_contact and 'id' in glific_contact:
            new_teacher.glific_id = glific_contact['id']
            new_teacher.save(ignore_permissions=True)

            # Enqueue Glific actions (optin and flow start) as a background job
            enqueue_glific_actions(
                new_teacher.name,
                data['phone'],
                data['firstName'],
                school,
                school_name,
                data.get('language', ''),
                model_name,
                data['batch_name'] 
            )

            frappe.db.commit()
            return {
                "status": "success",
                "message": "Teacher created successfully, Glific contact added or associated. Optin and flow start initiated.",
                "teacher_id": new_teacher.name,
                "glific_contact_id": new_teacher.glific_id
            }
        else:
            frappe.db.rollback()
            return {
                "status": "failure",
                "message": "Teacher created but failed to add or associate Glific contact",
                "teacher_id": new_teacher.name
            }

    except Exception as e:
        frappe.db.rollback()
        frappe.logger().error(f"Error in create_teacher_web: {str(e)}", exc_info=True)
        return {
            "status": "failure",
            "message": f"Error creating teacher: {str(e)}"
        }
    finally:
        frappe.flags.ignore_permissions = False







def get_course_level(course_vertical, grade, kitless):
    frappe.log_error(f"Input values: course_vertical={course_vertical}, grade={grade}, kitless={kitless}")

    query = """
        SELECT name FROM `tabStage Grades`
        WHERE CAST(%s AS INTEGER) BETWEEN CAST(from_grade AS INTEGER) AND CAST(to_grade AS INTEGER)
    """
    frappe.log_error(f"Stage query: {query[:100]}..." if len(query) > 100 else query)
    stage = frappe.db.sql(query, grade, as_dict=True)

    frappe.log_error(f"Stage result: {stage}")

    if not stage:
        # Check if there is a specific stage for the given grade
        query = """
            SELECT name FROM `tabStage Grades`
            WHERE CAST(from_grade AS INTEGER) = CAST(%s AS INTEGER) AND CAST(to_grade AS INTEGER) = CAST(%s AS INTEGER)
        """
        frappe.log_error(f"Specific stage query: {query[:100]}..." if len(query) > 100 else query)
        stage = frappe.db.sql(query, (grade, grade), as_dict=True)

        frappe.log_error(f"Specific stage result: {stage}")

        if not stage:
            frappe.throw("No matching stage found for the given grade")

    course_level = frappe.get_all(
        "Course Level",
        filters={
            "vertical": course_vertical,
            "stage": stage[0].name,
            "kit_less": kitless
        },
        fields=["name"],
        order_by="modified desc",
        limit=1
    )

    frappe.log_error(f"Course level query filters: vertical={course_vertical}, stage={stage[0].name}, kit_less={kitless}")
    frappe.log_error(f"Course level query: {frappe.as_json(course_level)}")

    if not course_level and kitless:
        # If no course level found with kit_less enabled, search for a course level without considering kit_less
        course_level = frappe.get_all(
            "Course Level",
            filters={
                "vertical": course_vertical,
                "stage": stage[0].name
            },
            fields=["name"],
            order_by="modified desc",
            limit=1
        )

        frappe.log_error(f"Fallback course level query filters: vertical={course_vertical}, stage={stage[0].name}")
        frappe.log_error(f"Fallback course level query: {frappe.as_json(course_level)}")

    if not course_level:
        frappe.throw("No matching course level found")

    return course_level[0].name







@frappe.whitelist(allow_guest=True)
def get_course_level_api():
    try:
        # Get the data from the request
        api_key = frappe.form_dict.get('api_key')
        grade = frappe.form_dict.get('grade')
        vertical = frappe.form_dict.get('vertical')
        batch_skeyword = frappe.form_dict.get('batch_skeyword')

        if not authenticate_api_key(api_key):
            frappe.throw("Invalid API key")

        # Validate required fields
        if not all([grade, vertical, batch_skeyword]):
            return {"status": "error", "message": "All fields are required"}

        # Get the school and batch from batch_skeyword
        batch_onboarding = frappe.get_all(
            "Batch onboarding",
            filters={"batch_skeyword": batch_skeyword},
            fields=["name", "kit_less"]
        )

        if not batch_onboarding:
            return {"status": "error", "message": "Invalid batch_skeyword"}

        kitless = batch_onboarding[0].kit_less

        # Get the course vertical using the label
        course_vertical = frappe.get_all(
            "Course Verticals",
            filters={"name2": vertical},
            fields=["name"]
        )

        if not course_vertical:
            return {"status": "error", "message": "Invalid vertical label"}

        # Get the appropriate course level based on the kitless option
        course_level = get_course_level(course_vertical[0].name, grade, kitless)

        return {
            "status": "success",
            "course_level": course_level
        }

    except frappe.ValidationError as e:
        frappe.log_error(f"Course Level API Validation Error: {str(e)}")
        return {"status": "error", "message": str(e)}
    except Exception as e:
        frappe.log_error(f"Course Level API Error: {str(e)}")
        return {"status": "error", "message": str(e)}




def get_model_for_school(school_id):
    today = frappe.utils.today()
    
    # Check for active batch onboardings
    active_batch_onboardings = frappe.get_all(
        "Batch onboarding",
        filters={
            "school": school_id,
            "batch": ["in", frappe.get_all("Batch", filters={"start_date": ["<=", today], "end_date": [">=", today], "active": 1}, pluck="name")]
        },
        fields=["model", "creation"],
        order_by="creation desc"
    )

    if active_batch_onboardings:
        # Use the model from the most recent active batch onboarding
        model_link = active_batch_onboardings[0].model
        frappe.logger().info(f"Using model from batch onboarding created on {active_batch_onboardings[0].creation} for school {school_id}")
    else:
        # If no active batch onboarding, fall back to school's default model
        model_link = frappe.db.get_value("School", school_id, "model")
        frappe.logger().info(f"No active batch onboarding found. Using default model for school {school_id}")

    # Get the model name from Tap Models
    model_name = frappe.db.get_value("Tap Models", model_link, "mname")
    
    if not model_name:
        frappe.logger().error(f"No model name found for model link {model_link}")
        raise ValueError(f"No model name found for school {school_id}")

    return model_name

