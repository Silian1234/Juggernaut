Shader "Hidden/Juggernaut/ThermalMask"
{
    SubShader
    {
        Pass
        {
            Cull Back
            ZWrite Off
            ZTest Always
            ColorMask R

            CGPROGRAM
            #pragma target 3.0
            #pragma vertex Vert
            #pragma fragment Frag
            #include "UnityCG.cginc"

            UNITY_DECLARE_DEPTH_TEXTURE(_CameraDepthTexture);

            struct Varyings
            {
                float4 position : SV_POSITION;
                float4 screenPosition : TEXCOORD0;
                float eyeDepth : TEXCOORD1;
            };

            Varyings Vert(float4 vertex : POSITION)
            {
                Varyings output;
                output.position = UnityObjectToClipPos(vertex);
                output.screenPosition = ComputeScreenPos(output.position);
                output.eyeDepth = -UnityObjectToViewPos(vertex).z;
                return output;
            }

            fixed4 Frag(Varyings input) : SV_Target
            {
                float rawDepth = SAMPLE_DEPTH_TEXTURE_PROJ(
                    _CameraDepthTexture, UNITY_PROJ_COORD(input.screenPosition));
                float sceneDepth = LinearEyeDepth(rawDepth);
                float tolerance = max(0.002, input.eyeDepth * 0.00005);
                clip(sceneDepth + tolerance - input.eyeDepth);
                return fixed4(1, 0, 0, 1);
            }
            ENDCG
        }
    }
    Fallback Off
}
