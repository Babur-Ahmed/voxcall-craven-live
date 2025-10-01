import time
import datetime
import subprocess
import pyaudio
import wave
import sys
import os
import errno
from numpy import short, array, chararray, frombuffer, log10, zeros
import traceback
from tkinter import *
from tkinter import ttk
from configparser import ConfigParser
import _thread
import urllib3
from shutil import copyfile
import logging
import json
import traceback
import re

#logging.basicConfig(filename='log.txt',filemode='w',level=logger.debug)

# create logger
logger = logging.getLogger('')
logger.setLevel(logging.DEBUG)

# create console handler and set level to debug
ch = logging.StreamHandler()
ch.setLevel(logging.DEBUG)

#create file handler and set level to debug
fh = logging.FileHandler('log.txt',mode='w')
fh.setLevel(logging.DEBUG)
# create formatter
formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')

# add formatter to ch
ch.setFormatter(formatter)
fh.setFormatter(formatter)

# add ch and fh to logger
logger.addHandler(ch)
logger.addHandler(fh)


#record_threshold = 800
vox_silence_time = 2
mp3_bitrate = 32000
start_minimized = 0
rectime = .1
rec_debounce_counter = 0
timeout_time_sec = 120
monitoring_active = False
monitoring_thread = None

# determine if application is a script file or frozen exe
if getattr(sys, 'frozen', False):
    version = os.path.basename(sys.executable).split('.')[0]
elif __file__:
    version = os.path.basename(__file__).split('.')[0]
    
config = ConfigParser()
config.read('config.cfg')

try:
    audio_dev_index = config.getint('Section1','audio_dev_index')
except:
    audio_dev_index = 0
try:
    record_threshold_config = config.getint('Section1','record_threshold')
except:
    record_threshold_config = 75
try:
    vox_silence_time = config.getfloat('Section1','vox_silence_time')
except:
    vox_silence_time = 3
try:
    in_channel_config = config.get('Section1','in_channel')
except:
    in_channel_config = 'mono'
try:
    BCFY_SystemId_config = config.get('Section1','BCFY_SystemId')
except:
    BCFY_SystemId_config = ''
try:
    BCFY_SlotId_config = config.get('Section1','BCFY_SlotId')
except:
    BCFY_SlotId_config = '1'
try:
    RadioFreq_config = config.get('Section1','RadioFreq')
except:
    RadioFreq_config = ''
try:
    BCFY_APIkey_config = config.get('Section1','BCFY_APIkey')
except:
    BCFY_APIkey_config = ''
try:
    saveaudio_config = config.getint('Section1','saveaudio')
except:
    saveaudio_config = 0
try:
    vox_silence_time = config.getfloat('Section','vox_silence_time')
except:
    vox_silence_time = 2
try:
    BCFY_APIurl_config = config.get('Section1','BCFY_APIurl')
except:
    BCFY_APIurl_config = 'https://calls.cravenlive.com/index.php'

try:
    root = Tk()
    if start_minimized==1:
        root.iconify()
    root.title('Voxcall - Craven Live')
except:
    root = ''

icon_path = os.path.join(getattr(sys, "_MEIPASS", os.path.dirname(__file__)), "voxcall.ico")
try:
    root.iconbitmap(icon_path)
    # Also set the taskbar icon for Windows
    if os.name == 'nt':  # Windows
        import ctypes
        myappid = 'voxcall.cravenlive.1.0'  # arbitrary string
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)
except:
    logger.warning("Could not load voxcall.ico")

# Initialize variables before try block
input_devices = []
input_device_indices = {}
inv_input_device_indices = {}

try:
    p = pyaudio.PyAudio()
    #list of the names of the audio input and output devices

    #FIND THE AUDIO DEVICES ON THE SYSTEM
    info = p.get_host_api_info_by_index(0)
    numdevices = info.get('deviceCount')

    #find index of pyaudio input and output devices
    for i in range (0,numdevices):
        if p.get_device_info_by_host_api_device_index(0,i).get('maxInputChannels')>0:
            input_devices.append(p.get_device_info_by_host_api_device_index(0,i).get('name'))
            input_device_indices[p.get_device_info_by_host_api_device_index(0,i).get('name')] = i
    
    # Create inverse mapping only if we found devices
    if input_devices:
        inv_input_device_indices = dict((v,k) for k,v in input_device_indices.items())
    
    p.terminate()
except:
    logging.exception('Got exception on main handler')

# Global flag to track if audio is available
audio_available = len(input_devices) > 0

if root != '':
    record_threshold = IntVar()
    record_threshold.set(record_threshold_config)
    #make sure the record_threshold value is not zero to avoid math issues
    if record_threshold.get() < 1:
        record_threshold.set(1)
    input_device = StringVar()
    output_device = StringVar()
    freqvar = StringVar()
    statvar = StringVar()
    if audio_available:
        statvar.set("Ready - Click Start Monitoring")
    else:
        statvar.set("NO AUDIO DEVICES FOUND")
    BCFY_APIkey = StringVar()
    BCFY_APIkey.set(BCFY_APIkey_config)
    BCFY_SystemId = StringVar()
    BCFY_SystemId.set(BCFY_SystemId_config)
    BCFY_SlotId = StringVar()
    BCFY_SlotId.set(BCFY_SlotId_config)
    RadioFreq = StringVar()
    RadioFreq.set(RadioFreq_config)
    saveaudio = IntVar()
    saveaudio.set(saveaudio_config)
    in_channel = StringVar()
    in_channel.set(in_channel_config)
    barvar = IntVar()
    barvar.set(10)
    BCFY_APIurl = StringVar()
    BCFY_APIurl.set(BCFY_APIurl_config)
    
    # Safe device selection - check if devices were found
    if input_devices:
        input_device.set(inv_input_device_indices.get(audio_dev_index,input_devices[0]))
    else:
        # Fallback if no audio devices detected
        input_device.set("No devices found")
        logger.error("No audio input devices found!")

RATE = 22050
chunk = 2205
FORMAT = pyaudio.paInt16

# Global recordstream variable
recordstream = None
pr = None

def start_audio_stream():
    global pr
    global recordstream
    
    if not audio_available:
        logger.error("Cannot start audio stream - no audio devices available")
        return
        
    try:
        pr = pyaudio.PyAudio()
        CHANNELS = 1
        if root != '':
            if in_channel.get() == 'left' or in_channel.get() == 'right':
                CHANNELS = 2 #chan
        else:
            if in_channel_config == 'left' or in_channel_config == 'right':
                CHANNELS = 2
        if root != '':
            # Check if device is valid before using it
            if input_device.get() not in input_device_indices:
                logger.error(f"Invalid audio device: {input_device.get()}")
                return
            index = input_device_indices[input_device.get()]
        else:
            index = audio_dev_index
        recordstream = pr.open(format = FORMAT,
                    channels = CHANNELS,
                    rate = RATE,
                    input = True,
                    output = True,
                    frames_per_buffer = chunk,
                    input_device_index = index,)
    except:
        logging.exception('Got exception on main handler')
        recordstream = None

if audio_available:
    start_audio_stream()

def change_audio_input(junk):
    if recordstream:
        recordstream.close()
    if pr:
        pr.terminate()
    start_audio_stream()
    
def record(seconds,channel='mono'):
    if not recordstream:
        # Return silence if no audio stream available
        return zeros(int(RATE * seconds), dtype=short)
        
    alldata = bytearray()
    for i in range(0, int(RATE / chunk * seconds)):
        data = recordstream.read(chunk)
        alldata.extend(data)
    data  = frombuffer(alldata, dtype=short)
    if channel == 'left':
        data = data[0::2]
    elif channel == 'right':
        data = data[1::2]
    else:
        data = data
    return data

def heartbeat():
    if (root != '' and BCFY_APIkey.get() != '') or (root == '' and BCFY_APIkey_config != ''):
        if root != '':
            url = BCFY_APIurl.get()
            apiKey = BCFY_APIkey.get()
            systemId = BCFY_SystemId.get()
        else:
            url = BCFY_APIurl_config
            apiKey = BCFY_APIkey_config
            systemId = BCFY_SystemId_config
        
        http = urllib3.PoolManager()
        r = http.request(
            'POST',
            url,
            fields={'apiKey': apiKey,'systemId': systemId,'test': '1'})
        if r.status != 200:
            logger.debug("heartbeat failed with status " + str(r.status))
            logger.debug(r.data)
        else:
            logger.debug("heartbeat OK at " + str(time.time()))

def upload(fname, duration):
    logger.debug(f"=== UPLOAD PROCESS STARTED ===")
    logger.debug(f"File: {fname}, Duration: {duration}")
    
    # Check if we should even attempt upload
    if (root != '' and BCFY_APIkey.get() != '') or (root == '' and BCFY_APIkey_config != ''):
        if root != '':
            url = BCFY_APIurl.get()
            apiKey = BCFY_APIkey.get()
            systemId = BCFY_SystemId.get()
            slotId = BCFY_SlotId.get()
            freq = RadioFreq.get()
        else:
            url = BCFY_APIurl_config
            apiKey = BCFY_APIkey_config
            systemId = BCFY_SystemId_config
            slotId = BCFY_SlotId_config
            freq = RadioFreq_config
            
        logger.debug(f"API Config - URL: {url}, SystemID: {systemId}, SlotID: {slotId}, Freq: {freq}")
        
        # Check if MP3 file exists
        if not os.path.exists(fname):
            logger.error(f"MP3 file does not exist: {fname}")
            return
            
        http = urllib3.PoolManager()
        
        # STEP 1: Request upload URL
        logger.debug("=== STEP 1: Requesting upload URL ===")
        try:
            r = http.request(
                'POST',
                url,
                fields={
                    'apiKey': apiKey,
                    'systemId': systemId,
                    'callDuration': str(duration),
                    'ts': fname.split('-')[0],  # Extract timestamp from filename
                    'tg': slotId,
                    'src': '0',
                    'freq': freq,
                    'enc': 'mp3'
                },
                timeout=30
            )
            
            logger.debug(f"Step 1 - Status Code: {r.status}")
            resp_text = r.data.decode('utf-8').strip()
            logger.debug(f"Step 1 - Raw Response: '{resp_text}'")
            
        except Exception as e:
            logger.error(f"Step 1 - Request failed: {str(e)}")
            return

        if r.status != 200:
            logger.error(f"Step 1 - Failed with status: {r.status}")
            return
            
        # Try multiple response format parsings
        upload_url = None
        
        # Format 1: Space-separated "0 http://url"
        if ' ' in resp_text:
            parts = resp_text.split(' ')
            if len(parts) >= 2 and parts[0] == '0':
                upload_url = parts[1].strip()
                logger.debug(f"Parsed URL (space format): {upload_url}")
        
        # Format 2: JSON response (common in APIs)
        if not upload_url and resp_text.startswith('{'):
            try:
                json_data = json.loads(resp_text)
                if 'url' in json_data:
                    upload_url = json_data['url']
                elif 'uploadUrl' in json_data:
                    upload_url = json_data['uploadUrl']
                logger.debug(f"Parsed URL (JSON format): {upload_url}")
            except json.JSONDecodeError:
                logger.warning("Response looks like JSON but failed to parse")
        
        # Format 3: Direct URL (just the URL)
        if not upload_url and (resp_text.startswith('http://') or resp_text.startswith('https://')):
            upload_url = resp_text
            logger.debug(f"Parsed URL (direct format): {upload_url}")
        
        if not upload_url:
            logger.error(f"Could not parse upload URL from response: '{resp_text}'")
            # Try to extract URL using regex as last resort
            url_match = re.search(r'(https?://[^\s]+)', resp_text)
            if url_match:
                upload_url = url_match.group(1)
                logger.debug(f"Extracted URL via regex: {upload_url}")
            else:
                logger.error("No URL found in API response")
                return
        
        # STEP 2: Upload the file
        logger.debug("=== STEP 2: Uploading MP3 file ===")
        try:
            with open(fname, "rb") as f:
                file_data = f.read()
            
            r1 = http.request(
                'PUT',
                upload_url,
                body=file_data,
                headers={'Content-Type': 'audio/mpeg'},
                timeout=60
            )
            
            logger.debug(f"Step 2 - Status Code: {r1.status}")
            if r1.status == 200:
                logger.debug("=== UPLOAD SUCCESS ===")
            else:
                logger.error(f"Upload failed with status: {r1.status}")
                logger.error(f"Response: {r1.data.decode('utf-8')}")
                
        except Exception as e:
            logger.error(f"Upload failed: {str(e)}")
    else:
        logger.info("No API config found, skipping upload")
        
def cleanup_audio_files(fname):
    if root != '':
        saveit = saveaudio.get()
    else:
        saveit = saveaudio_config
        
    # Extract base filename without extension
    base_name = os.path.splitext(fname)[0]
    mp3_file = base_name + '.mp3'
    m4a_file = base_name + '.m4a'
    
    if saveit != 0:
        try:
            os.makedirs('./audiosave', exist_ok=True)
            logger.debug("Moving mp3 file for archiving")
            if os.path.exists(mp3_file):
                copyfile(mp3_file, './audiosave/' + os.path.basename(mp3_file))
        except Exception as e:
            logger.error(f"Error saving audio: {str(e)}")
    
    # Wait for upload to complete
    time.sleep(10)
    
    logger.debug("Removing temporary audio files")
    try:
        if os.path.exists(mp3_file):
            os.remove(mp3_file)
        if os.path.exists(m4a_file):
            os.remove(m4a_file)
    except Exception as e:
        logger.error(f"Error cleaning up files: {str(e)}")

def start():
    global rec_debounce_counter
    last_API_attempt = 0
    
    if not audio_available:
        logger.error("Cannot start - no audio devices available")
        if root != '':
            statvar.set("NO AUDIO DEVICES")
            StatLabel.config(fg='red')
        return
    
    #wait for audio to be present
    counter = 0
    while 1:
        if time.time()-last_API_attempt > 10*60:
            _thread.start_new_thread(heartbeat,())  #ping the API every 10 minutes so it knows we're alive
            last_API_attempt = time.time()
        #get 100 ms of audio
        if root != '':
            chan = in_channel.get()
        else:
            chan = in_channel_config
        audio_data = record(rectime,chan)
        if max(abs(audio_data)) == 0 and root != '':
                barvar.set(1)
        elif counter >=6 and root != '':
            #set the bar graph display based on the current audio peak using a log scale
            barvar.set(max(100-int(log10(max(max(abs(audio_data)),1.0)/32768.)*10/-25.*100),3))  #min of scale is -25 dB
            counter = 0
        counter = counter + 1
        if root != '':
            if 100-log10(max(max(abs(audio_data)),1.0)/32768.)*10/-25.*100 > record_threshold.get() or record_threshold.get()==0:
                rec_debounce_counter = rec_debounce_counter + 1
                logger.debug('Level: ' + str(100-log10(max(max(abs(audio_data)),1.0)/32768.)*10/-25.*100) + " Threshold: " + str(record_threshold.get()))
            else:
                rec_debounce_counter = 0
        else:
            if  max(abs(audio_data))> record_threshold_config:
                rec_debounce_counter = rec_debounce_counter + 1
                logger.debug('Level: ' + str(max(abs(audio_data))) + " Threshold: " + str(record_threshold_config))
            else:
                rec_debounce_counter = 0
        if rec_debounce_counter >=2:
            rec_debounce_counter = 0
            logger.debug("threshold exceeded")
            start_time = time.time()
            quiet_samples=0
            total_samples = 0
            alldata = bytearray()
            logger.debug("Waiting for Silence " + time.strftime('%H:%M:%S on %m/%d/%y'))
            if root != '':
                statvar.set("Recording")
                StatLabel.config(fg='green')
            timed_out = 0
            while (quiet_samples < (vox_silence_time*(1/rectime))):
                if (total_samples > (timeout_time_sec*(1/rectime))):
                    if root != '':
                        statvar.set("RECORDING TIMED OUT")
                        StatLabel.config(fg='red')
                    else:
                        logger.debug("RECORDING TIMED OUT")
                    timed_out = 1
                temp =bytearray()
                for i in range(0, int(RATE / chunk * rectime)):
                    data = recordstream.read(chunk)
                    temp.extend(data)
                if timed_out == 0:
                    alldata.extend(temp)
                audio_data  = frombuffer(temp, dtype=short)
                if root != '':
                    if max(abs(audio_data)) == 0:
                        barvar.set(1)
                    else:
                        #set the bar graph display based on the current audio peak using a log scale
                        barvar.set(max(100-int(log10(max(max(abs(audio_data)),1.0)/32768.)*10/-25.*100),3))  #min of scale is -25 dB
                if root != '':
                    if 100-log10(max(max(abs(audio_data)),1.0)/32768.)*10/-25.*100 < record_threshold.get() and record_threshold.get()!=0:
                        quiet_samples = quiet_samples+1
                    else:
                        quiet_samples = 0
                else:
                    if max(abs(audio_data)) < record_threshold_config:
                        quiet_samples = quiet_samples+1
                    else:
                        quiet_samples = 0
                total_samples = total_samples+1
            logger.debug("Done recording " + time.strftime('%H:%M:%S on %m/%d/%y'))
            if int(vox_silence_time*-(1/rectime)) > 0:
                alldata = alldata[:int(vox_silence_time*-round(1/rectime))]
            data = frombuffer(alldata, dtype=short)  #convert from string to list to separate channels
            if chan == 'left':
                data = data[0::2]
            elif chan == 'right':
                data = data[1::2]
            else:
                data = data
            duration = len(data)/float(RATE)
            data = chararray.tobytes(array(data))
            # write data to WAVE file
            fname = str(round(time.time())) + "-" + str(BCFY_SlotId.get()) + ".wav"
            WAVE_OUTPUT_FILENAME = fname

            wf = wave.open(WAVE_OUTPUT_FILENAME, 'wb')
            wf.setnchannels(1)
            wf.setsampwidth(pyaudio.PyAudio().get_sample_size(FORMAT))
            wf.setframerate(RATE)
            wf.writeframes(data)
            wf.close()
            logger.debug("done writing WAV "  + time.strftime('%H:%M:%S on %m/%d/%y'))
            try:            
                logger.debug(fname)
                try:
                    flags = subprocess.CREATE_NO_WINDOW
                except:
                    flags = 0
                subprocess.call(["ffmpeg","-y","-i",fname,"-b:a",str(mp3_bitrate),"-ar","22050",fname.replace('.wav','.mp3')],creationflags=flags)
                logger.debug("done converting to MP3 " + time.strftime('%H:%M:%S on %m/%d/%y'))
                subprocess.call(["ffmpeg","-y","-i",fname,"-b:a",str(mp3_bitrate),"-ar","22050",fname.replace('.wav','.m4a')],creationflags=flags)
                logger.debug("done converting to M4A " + time.strftime('%H:%M:%S on %m/%d/%y'))
                os.remove(fname)
            except:
                logging.exception('Got exception on main handler')
            mp3_filename = fname.replace('.wav','.mp3')
            if os.path.exists(mp3_filename):
                mp3_size = os.path.getsize(mp3_filename)
                logger.debug(f"MP3 conversion successful: {mp3_filename} ({mp3_size} bytes)")
            else:
                logger.error(f"MP3 conversion failed: {mp3_filename} does not exist")
            try:
                mp3_file = fname.replace('.wav','.mp3')
                logger.debug(f"Starting upload thread for: {mp3_file}")
                _thread.start_new_thread(upload, (mp3_file, duration))
            except Exception as e:
                logger.error(f"Failed to start upload thread: {str(e)}")
            _thread.start_new_thread(cleanup_audio_files,(fname,))
            last_API_attempt = time.time()
            logger.debug("duration: " + str(duration) + " sec")
            logger.debug("waiting for audio " + time.strftime('%H:%M:%S on %m/%d/%y'))
            if root != '':
                statvar.set("Waiting For Audio")
                StatLabel.config(fg='blue')

def start_monitoring():
    global monitoring_active, monitoring_thread
    if not monitoring_active and audio_available:
        monitoring_active = True
        statvar.set("Starting...")
        monitoring_thread = _thread.start_new_thread(start, ())
        statvar.set("Monitoring - Waiting For Audio")
        StatLabel.config(fg='blue')
        logger.info("Monitoring started")
    elif not audio_available:
        statvar.set("No Audio Devices!")
        StatLabel.config(fg='red')

def stop_monitoring():
    global monitoring_active
    monitoring_active = False
    statvar.set("Stopped")
    StatLabel.config(fg='red')
    logger.info("Monitoring stopped")

def saveconfigdata():
    if root != '':
        config = ConfigParser()
        config.read('config.cfg')
        if 'Section1' not in config.sections():
            config.add_section('Section1')
        cfgfile = open('config.cfg','w')
        
        # Safe device index saving
        if input_device.get() in input_device_indices:
            config.set('Section1','audio_dev_index',str(input_device_indices[input_device.get()]))
        else:
            # Save the original index if current device is invalid
            config.set('Section1','audio_dev_index',str(audio_dev_index))
            
        config.set('Section1','record_threshold',str(record_threshold.get()))
        config.set('Section1','vox_silence_time',str(vox_silence_time))
        config.set('Section1','in_channel',in_channel.get())
        config.set('Section1','BCFY_SystemId',BCFY_SystemId.get())
        config.set('Section1','RadioFreq',RadioFreq.get())
        config.set('Section1','BCFY_APIkey',BCFY_APIkey.get())
        config.set('Section1','BCFY_SlotId',BCFY_SlotId.get())
        config.set('Section1','saveaudio',str(saveaudio.get()))
        config.set('Section1','vox_silence_time',str(vox_silence_time))
        config.set('Section1','BCFY_APIurl',BCFY_APIurl.get())
        config.write(cfgfile)
        cfgfile.close()
        root.destroy()

if root != '':
    f = Frame(bd=10)
    f.grid(row = 1)

    def validate_number(P): 
        if str.isdigit(P) or P == "":
            return True
        else:
            return False
    vcmd = (f.register(validate_number),"%P") 

    StatLabel = Label(f,textvar = statvar,font=("Helvetica", 12))
    StatLabel.grid(row = 1, column = 1,columnspan = 4,sticky = W)
    if audio_available:
        StatLabel.config(fg='blue')
    else:
        StatLabel.config(fg='red')
        
    Label(f, text="Audio Input Device:").grid(row = 3, column = 0,sticky = E)
    if input_devices:
        OptionMenu(f, input_device, input_device.get(), *input_devices, command=change_audio_input).grid(row=3, column=1, columnspan=4, sticky=E+W)
    else:
        # Show disabled menu if no devices
        OptionMenu(f, input_device, "No devices found").grid(row=3, column=1, columnspan=4, sticky=E+W)
        
    Label(f,text = 'Audio Input Channel').grid(row = 5,column = 0,sticky=E)
    audiochannellist = OptionMenu(f,in_channel,"mono","left","right")
    audiochannellist.config(width=20)
    audiochannellist.grid(row = 5,column = 1,sticky=W)
    Label(f,text='General Settings').grid(row=6,column=1,sticky = W)
    Label(f,text='Radio Frequency (MHz):').grid(row=7,column=0,sticky = E)
    
    Freq_Entry = Entry(f,width=20,textvariable = RadioFreq)
    Freq_Entry.grid(row = 7, column = 1,sticky=W)
    Label(f,text='Save Audio Files:').grid(row=8,column=0,sticky=E)
    Checkbutton(f,text = '',variable = saveaudio).grid(row = 8, column = 1,sticky=W)
    
    Label(f,text='API Settings').grid(row=9,column=1,sticky = W)
    Label(f,text='API URL:').grid(row=10,column=0,sticky = E)
    BCFY_APIurl_Entry = Entry(f,width=40,textvariable = BCFY_APIurl)
    BCFY_APIurl_Entry.grid(row = 10, column = 1,columnspan = 4,sticky=W)
    Label(f,text='API Key:').grid(row=11,column=0,sticky = E)
    BCFY_APIkey_Entry = Entry(f,width=40,textvariable = BCFY_APIkey)
    BCFY_APIkey_Entry.grid(row = 11, column = 1,columnspan = 4,sticky=W)
    Label(f,text='System ID:').grid(row=12,column=0,sticky = E)
    BCFY_SystemId_Entry = Entry(f,width=20,validate='key',validatecommand=vcmd,textvariable = BCFY_SystemId)
    BCFY_SystemId_Entry.grid(row = 12, column = 1,sticky=W)
    Label(f,text='Slot ID:').grid(row=13,column=0,sticky = E)
    BCFY_SlotId_Entry = Entry(f,width=20,validate='key',validatecommand=vcmd,textvariable = BCFY_SlotId)
    BCFY_SlotId_Entry.grid(row = 13, column = 1,sticky=W)

    Button(f, text="Save Config", command=saveconfigdata, width=15).grid(row=30, column=0, sticky=W)
    Button(f, text="Start Monitoring", command=start_monitoring, width=15).grid(row=30, column=1, sticky=W)
    Button(f, text="Stop Monitoring", command=stop_monitoring, width=15).grid(row=30, column=2, sticky=W)

    squelchbar = Scale(f,from_ = 100, to = 0,length = 150,sliderlength = 8,showvalue = 0,variable = record_threshold,orient = 'vertical').grid(row = 17,rowspan=8,column = 7,columnspan = 1)
    ttk.Progressbar(f,orient ='vertical',variable = barvar,length = 150).grid(row = 17,rowspan = 8,column = 8,columnspan = 1)
    Label(f,text='Audio\n Squelch').grid(row=25,column=7)
    Label(f,text='Audio\n Level').grid(row=25,column=8)
    

if root != '':
    # Don't start automatically - wait for user to click "Start Monitoring"
    if audio_available:
        statvar.set("Ready - Click Start Monitoring")
        StatLabel.config(fg='green')
    else:
        statvar.set("NO AUDIO DEVICES FOUND")
        StatLabel.config(fg='red')
    root.mainloop()
else:
    # Command line mode - start automatically
    if audio_available:
        start()
    else:
        logger.error("Application started but no audio devices available")
