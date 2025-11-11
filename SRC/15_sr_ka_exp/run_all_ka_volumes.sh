#!/bin/bash -x

# Single function to extract, and validate.
# Call with:
# run_extraction <filename> <start> <end>
function run_extraction(){
  filename=${1}
  start=${2}
  end=${3}

  # Change the prompt name here:
  prompt=PROMPTS/15_sr_ka_exp/15_sr_ka_exp_v2.md

  # Output path
  out_path=OUT/18_viki_ka_cost

  # Location of the .output file.  Needs to be present before we start otherwise
  # the shell >> redirect fails.
  mkdir -p ${out_path}/${filename%.pdf}
  
  SRC/15_sr_ka_exp/extract_workflow.py \
  --file-path DATA/All_States/KA_2020-21/${filename} \
  --prompt-path ${prompt} \
  --start-page ${start} \
  --end-page ${end} \
  --out-path ${out_path}/${filename%.pdf} \
  >> ${out_path}/${filename%.pdf}/${filename%.pdf}.output &
}

# In parallel, run all Karnataka volumes
run_extraction 03-EXPVOL-01-1.pdf 14 241

run_extraction 04-EXPVOL-02.pdf 9 188

run_extraction 05-EXPVOL-03.pdf 9 146

run_extraction 06-EXPVOL-04.pdf 9 151

run_extraction 07-EXPVOL-05.pdf 12 193

run_extraction 08-EXPVOL-06.pdf 10 84

run_extraction 09-EXPVOL-07.pdf 9 121

